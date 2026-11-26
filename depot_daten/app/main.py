"""Depot-Daten 0.2 – holt täglich Eulerpool-Daten zu Depot- und Beobachtungstiteln nach Home Assistant.

Titel: alle Sensoren mit Label `beobachtungsliste` oder `depot_einzelaktie`.
Ausgabe (MQTT-Discovery, Gerät „Depot-Daten“):
  sensor.depotdaten_<titel>          Zustand = Abstand zum Kursziel in %, Attribute = alle Kennzahlen
  sensor.depotdaten_status           ok / Fehler, Attribute: Titel, Hinweise, Fehler
  sensor.depotdaten_abrufe_heute     Eulerpool-Abrufe heute
  sensor.depotdaten_abrufe_monat     Eulerpool-Abrufe diesen Monat (Attribut: Limit, Verlauf)
  sensor.depotdaten_abrufe_rest      verbleibende Abrufe laut Eulerpool (X-RateLimit-Remaining)
  sensor.depotdaten_letzter_lauf     Zeitpunkt des letzten Laufs
  button.depotdaten_aktualisieren    sofort neu holen
Zusätzlich: input_text.watchlist_<titel>_kennzahlen (kurze Zeile für die Beobachtungsliste), falls vorhanden.
"""

import json
import logging
import re
import threading
import time
from datetime import date, datetime
from pathlib import Path

import ha
import titles
from eulerpool import Eulerpool
from usage import Usage

VERSION = "0.2.0"
OPTIONS_FILE = Path("/data/options.json")
CACHE_FILE = Path("/data/isin_cache.json")
LAST_FILE = Path("/data/last_results.json")
SECRETS = (Path("/homeassistant/secrets.yaml"), Path("/config/secrets.yaml"))
LABELS = ["beobachtungsliste", "depot_einzelaktie"]

log = logging.getLogger("depot_daten")
run_now = threading.Event()


def load_json(p, default):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return default


def load_token(opts):
    tok = (opts.get("token") or "").strip()
    if tok:
        return tok
    for f in SECRETS:
        try:
            for line in f.read_text().splitlines():
                m = re.match(r"^\s*eulerpool_token\s*:\s*(.+?)\s*$", line)
                if m:
                    return m.group(1).strip().strip("'\"")
        except OSError:
            continue
    return None


def parse_overrides(lines):
    out = {}
    for s in lines or []:
        if "=" in s:
            k, v = s.split("=", 1)
            out[k.strip()] = v.strip()
    return out


class App:
    def __init__(self, opts):
        self.opts = opts
        self.limit = int(opts.get("monatslimit") or 100000)
        self.usage = Usage()
        self.api = Eulerpool(load_token(opts), self.usage)
        self.cache = load_json(CACHE_FILE, {})
        self.overrides = parse_overrides(opts.get("isin_zuordnung"))
        self.known = set(load_json(LAST_FILE, {}).keys())
        self.retry_at = 0.0
        self.mq = ha.Mqtt(self.on_command)
        time.sleep(2)
        self.announce_fixed()
        self.publish_usage()

    # ---------- MQTT ----------
    def on_command(self, topic, payload):
        if topic.endswith("/aktualisieren"):
            log.info("Knopf „Jetzt aktualisieren“ gedrückt")
            run_now.set()
        elif topic == f"{ha.DISC}/status" and payload == "online":
            log.info("Home Assistant neu gestartet – Discovery erneut senden")
            threading.Timer(5, self.republish).start()

    def announce_fixed(self):
        m = self.mq
        m.sensor("status", "Status", "mdi:database-check")
        m.sensor("abrufe_heute", "Abrufe heute", "mdi:counter", unit="Abrufe", state_class="measurement",
                 attrs=False)
        m.sensor("abrufe_monat", "Abrufe diesen Monat", "mdi:chart-donut", unit="Abrufe",
                 state_class="measurement")
        m.sensor("abrufe_rest", "Abrufe übrig (Eulerpool)", "mdi:battery-charging-medium", unit="Abrufe",
                 state_class="measurement")
        m.sensor("letzter_lauf", "Letzter Abruf", "mdi:clock-check-outline", device_class="timestamp",
                 attrs=False)
        m.button("aktualisieren", "Jetzt aktualisieren", "mdi:refresh")

    def republish(self):
        self.announce_fixed()
        last = load_json(LAST_FILE, {})
        for key, o in last.items():
            self.announce_title(key, o.get("titel", key))
            self.mq.state(key, o.get("abstand_pct"), o)
        self.publish_usage()

    def announce_title(self, key, name):
        self.mq.sensor(key, name, "mdi:chart-box-outline", unit="%", state_class="measurement")

    def publish_usage(self):
        rate = self.api.rate
        rest = rate.get("remaining")
        self.mq.state("abrufe_heute", self.usage.today)
        self.mq.state("abrufe_monat", self.usage.month, {
            "monatslimit": self.limit,
            "verbraucht_pct": round(self.usage.month / self.limit * 100, 2) if self.limit else None,
            "verlauf": self.usage.history,
            "eulerpool_limit": rate.get("limit"), "eulerpool_reset": rate.get("reset")})
        self.mq.state("abrufe_rest", rest if rest not in (None, "") else None,
                      {"limit": rate.get("limit"), "reset": rate.get("reset"),
                       "hinweis": "Werte aus den X-RateLimit-Antwortköpfen von Eulerpool"})
        self.usage.save()

    # ---------- Lauf ----------
    def run(self):
        if not self.api.token:
            log.error("Kein Eulerpool-Schlüssel (Feld token leer, kein eulerpool_token in secrets.yaml)")
            self.mq.state("status", "kein Schlüssel", {"version": VERSION})
            self.retry_at = time.time() + 1800
            return
        t0 = time.time()
        calls0 = self.usage.month
        today = date.today()
        self.mq.state("status", "läuft", {"version": VERSION, "start": datetime.now().isoformat(timespec="seconds")})
        try:
            found = ha.find_titles(LABELS)
        except Exception as e:
            log.error("Titel aus HA lesen fehlgeschlagen: %s", e)
            self.mq.state("status", "Fehler", {"fehler": f"HA: {e}", "version": VERSION})
            self.retry_at = time.time() + 600
            return
        results, skipped, errors, flagged = {}, {}, {}, {}
        for t in found:
            name = t.get("name") or t["entity"]
            sym = t.get("symbol") or ""
            if sym in titles.SKIP:
                skipped[name] = titles.SKIP[sym]
                continue
            try:
                isin = titles.resolve_isin(self.api, t, self.cache, self.overrides)
                if not isin:
                    skipped[name] = "bei Eulerpool nicht gefunden"
                    continue
                raw = titles.collect(self.api, t, isin, today)
                o = titles.evaluate(self.api, t, isin, raw, self.cache, today)
                o["entity"] = t["entity"]
                o["labels"] = t.get("labels")
                o["stand"] = datetime.now().astimezone().isoformat(timespec="seconds")
                key = ha.slug(name)
                self.announce_title(key, name)
                self.mq.state(key, o.get("abstand_pct"), o)
                results[key] = o
                if o["pruefen"]:
                    flagged[name] = o["hinweise"]
                kz = f"input_text.watchlist_{ha.slug(name)}_kennzahlen"
                if "beobachtungsliste" in (t.get("labels") or []) and ha.state_exists(kz):
                    ha.set_input_text(kz, o["kennzahlen"])
                log.info("%-22s %s", name, o["kennzahlen"])
            except Exception as e:  # ein Titel darf den Lauf nicht abbrechen
                log.exception("%s: Fehler", name)
                errors[name] = str(e).replace(self.api.token or "§", "***")[:200]
            self.publish_usage()
        # verschwundene Titel aus HA entfernen
        for key in self.known - set(results):
            if key not in {ha.slug(n) for n in skipped}:
                self.mq.remove(key)
        self.known = set(results)
        LAST_FILE.write_text(json.dumps(results, ensure_ascii=False, default=str))
        CACHE_FILE.write_text(json.dumps(self.cache))
        now = datetime.now().astimezone()
        self.usage.set("last_run", now.isoformat())
        self.mq.state("letzter_lauf", now.isoformat(timespec="seconds"))
        status = "ok" if not errors else f"{len(errors)} Fehler"
        self.mq.state("status", status, {
            "version": VERSION, "titel": len(results), "titel_liste": sorted(o["titel"] for o in results.values()),
            "ohne_daten": skipped, "pruefen": flagged, "fehler": errors,
            "abrufe_letzter_lauf": self.usage.month - calls0, "dauer_s": round(time.time() - t0),
            "laeuft_taeglich_um": self.opts.get("uhrzeit", "05:00"),
            "stand": now.isoformat(timespec="seconds")})
        self.publish_usage()
        log.info("Fertig: %d Titel, %d Abrufe, %d ohne Daten, %d mit Hinweis, %d Fehler",
                 len(results), self.usage.month - calls0, len(skipped), len(flagged), len(errors))

    def due(self):
        if time.time() < self.retry_at:
            return False
        hhmm = self.opts.get("uhrzeit", "05:00")
        last = self.usage.get("last_run")
        last_d = datetime.fromisoformat(last).date() if last else None
        now = datetime.now()
        if last_d is None:
            return True
        return last_d < now.date() and now.strftime("%H:%M") >= hhmm


def main():
    opts = load_json(OPTIONS_FILE, {})
    logging.basicConfig(level=getattr(logging, str(opts.get("log_level", "info")).upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    log.info("Depot-Daten %s startet", VERSION)
    app = App(opts)
    while True:
        if run_now.is_set() or app.due():
            run_now.clear()
            try:
                app.run()
            except Exception:
                log.exception("Lauf fehlgeschlagen")
                app.mq.state("status", "Fehler", {"version": VERSION})
        run_now.wait(30)


if __name__ == "__main__":
    main()
