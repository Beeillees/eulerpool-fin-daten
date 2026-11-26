"""Depot-Tagebuch: Tageskurse und Bestände dauerhaft speichern, Käufe/Verkäufe erkennen.

Datei: /homeassistant/www/depot-daten/verlauf.json  (im Browser: /local/depot-daten/verlauf.json)
{
  "version": 1, "aktualisiert": ISO,
  "kurse":     {SYMBOL: [[YYYY-MM-DD, Schlusskurs in Originalwährung], ...]},
  "quellen":   {SYMBOL: {"yahoo_ab": Datum, "eulerpool_bis": Datum | null}},
  "bestand":   {key: [[Datum, Stück, Einstand], ...]}   # nur Tage mit Änderung
  "buchungen": [[Datum, key, Stück-Änderung, Einstand-Änderung, "erkannt"], ...]
}
Positionen und Symbole liest die App aus der Depot-Karte im Dashboard (/homeassistant/.storage/lovelace.*),
damit beides immer zusammenpasst.
"""

import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import ha
from titles import lst, num, to_date

log = logging.getLogger("depot_daten.verlauf")
CONFIG = Path("/homeassistant")
OUT_DIR = CONFIG / "www" / "depot-daten"
OUT = OUT_DIR / "verlauf.json"
EXTRA_SYMBOLS = ["EURUSD=X", "EUNL.DE"]   # Wechselkurs und MSCI-World-Vergleich der Karte

# ISIN je Yahoo-Symbol für die einmalige Nachfüllung älterer Tageskurse über Eulerpool
BACKFILL_ISIN = {
    "EUNL.DE": "IE00B4L5Y983", "EUNM.DE": "IE00B4L5YC18", "DFEN.DE": "IE000YYE6WK5", "ASWC.DE": "IE000OJ5TQP4",
    "XAIX.DE": "IE00BGV5VN51", "4GLD.DE": "DE000A0S9GB0", "BRK-B": "US0846707026", "GOOGL": "US02079K3059",
    "NKE": "US6541061031", "RKLB": "US7731211089", "MSTR": "US5949724083",
}


def load():
    try:
        d = json.loads(OUT.read_text())
        if isinstance(d, dict):
            for k, v in (("kurse", {}), ("quellen", {}), ("bestand", {}), ("buchungen", [])):
                d.setdefault(k, v)
            return d
    except (OSError, ValueError):
        pass
    return {"version": 1, "kurse": {}, "quellen": {}, "bestand": {}, "buchungen": []}


KEEP_FROM = "2023-01-01"   # älter braucht die Karte nicht (erste Käufe 2023)


def sanitize(d):
    """Alte Kurse abschneiden; Eulerpool-Nachfüllung bis zum letzten unplausiblen Tagessprung verwerfen
    (unbereinigte Splits). Yahoo-Tage bleiben immer."""
    for sym, rows in d["kurse"].items():
        rows = [r for r in rows if r[0] >= KEEP_FROM]
        q = d["quellen"].get(sym, {})
        ep_bis = q.get("eulerpool_bis")
        if ep_bis:
            cut = None
            for a, b in zip(rows, rows[1:]):
                if b[0] > ep_bis:
                    break
                ratio = b[1] / a[1] if a[1] else 1
                if ratio > 1.8 or ratio < 0.55:
                    cut = b[0]
            if cut:
                rows = [r for r in rows if r[0] >= cut or r[0] > ep_bis]
                q["eulerpool_gekuerzt_ab"] = cut
            if not any(r[0] <= ep_bis for r in rows):
                q.pop("eulerpool_bis", None)
        d["kurse"][sym] = rows


def save(d):
    sanitize(d)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    d["aktualisiert"] = datetime.now().astimezone().isoformat(timespec="seconds")
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")))
    os.replace(tmp, OUT)


def positions():
    """Positionen der Depot-Karte aus den gespeicherten Dashboards (nur lesen)."""
    found = {}
    for f in sorted((CONFIG / ".storage").glob("lovelace*")):
        try:
            data = json.loads(f.read_text())
        except (OSError, ValueError):
            continue

        def walk(o):
            if isinstance(o, dict):
                if o.get("type") == "custom:depot-performance-card" and isinstance(o.get("positions"), list):
                    for p in o["positions"]:
                        if p.get("key") and p.get("symbol"):
                            found.setdefault(p["key"], p)
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(data)
    return list(found.values())


def merge_prices(d, sym, rows, source):
    """rows: [[iso, preis]]; überschreibt gleiche Tage (Yahoo gewinnt gegen Eulerpool)."""
    cur = {r[0]: r[1] for r in d["kurse"].get(sym, [])}
    added = 0
    for day, p in rows:
        if not day or p is None or p <= 0:
            continue
        if day not in cur:
            added += 1
        if source == "yahoo" or day not in cur:
            cur[day] = round(float(p), 6)
    d["kurse"][sym] = sorted([k, v] for k, v in cur.items())
    return added


def easy_stock_history(sym):
    res = ha._req(f"{ha.CORE}/easy_stock/history?symbol={urllib.request.quote(sym)}", timeout=60)
    rows = res.get("history", []) if isinstance(res, dict) else []
    out = []
    for r in rows:
        if isinstance(r, (list, tuple)) and len(r) >= 2:
            dd = to_date(r[0])
            out.append([dd.isoformat() if dd else None, num(r[1])])
    return out


def update_prices(d, syms):
    """Tageskurse aus Easy Stock (Yahoo, ~1 Jahr) dauerhaft übernehmen. Kostet keine Eulerpool-Abrufe."""
    stats = {}
    for sym in syms:
        try:
            rows = easy_stock_history(sym)
        except Exception as e:
            stats[sym] = f"Fehler: {e}"
            continue
        n = merge_prices(d, sym, rows, "yahoo")
        q = d["quellen"].setdefault(sym, {})
        if rows:
            first = min(r[0] for r in rows if r[0])
            q["yahoo_ab"] = min(q.get("yahoo_ab") or first, first)
        stats[sym] = f"+{n} Tage" if n else "aktuell"
    return stats


def _candles(api, isin):
    """Ältere Tageskurse von Eulerpool; mehrere mögliche Abrufe, Antwortform defensiv lesen."""
    tries = [("equity/candles/" + isin, {"range": "max"}), ("etf/quotes/" + isin, {}),
             ("equity/quotes/" + isin, {"startdate": int(datetime(2023, 1, 1).timestamp() * 1000)})]
    for path, params in tries:
        st, data = api.get(path, **params)
        rows = data if isinstance(data, list) else lst(data, "data") or lst(data, "candles") or lst(data, "quotes")
        out = {}
        for r in rows:
            if isinstance(r, dict):
                dd = to_date(r.get("date") or r.get("timestamp") or r.get("t") or r.get("time"))
                p = num(r.get("close") if r.get("close") is not None else r.get("c") if r.get("c") is not None
                        else r.get("price"))
            elif isinstance(r, (list, tuple)) and len(r) >= 2:
                dd, p = to_date(r[0]), num(r[-2] if len(r) >= 5 else r[1])
            else:
                continue
            if dd and p:
                out[dd.isoformat()] = p   # bei mehreren Werten am Tag gewinnt der letzte
        if len(out) > 30:
            return path.split("/")[0] + "/" + path.split("/")[1], sorted(out.items())
    return None, []


def backfill(d, api, syms):
    """Einmalig: Tage vor dem Yahoo-Jahr mit Eulerpool füllen, nur wenn sich die Kurse im
    gemeinsamen Zeitraum decken (Median-Abweichung < 3 %, gleiche Währung/Einheit)."""
    report = {}
    for sym in syms:
        q = d["quellen"].setdefault(sym, {})
        if q.get("eulerpool_geprueft"):
            continue
        isin = BACKFILL_ISIN.get(sym)
        if not isin:
            q["eulerpool_geprueft"] = True
            report[sym] = "keine ISIN"
            continue
        src, rows = _candles(api, isin)
        q["eulerpool_geprueft"] = True
        if not rows:
            report[sym] = "Eulerpool ohne Tageskurse"
            continue
        have = {r[0]: r[1] for r in d["kurse"].get(sym, [])}
        overlap = [(p, have[day]) for day, p in rows if day in have]
        if len(overlap) < 20:
            report[sym] = f"zu wenig Überschneidung ({len(overlap)} Tage)"
            continue
        ratios = sorted(a / b for a, b in overlap if b)
        med = ratios[len(ratios) // 2]
        if not 0.97 <= med <= 1.03:
            report[sym] = f"passt nicht (Faktor {med:.3f})"
            continue
        start = q.get("yahoo_ab") or min(have)
        older = [[day, p] for day, p in rows if day < start]
        n = merge_prices(d, sym, older, "eulerpool")
        if older:
            q["eulerpool_bis"] = max(r[0] for r in older)
            q["eulerpool_ab"] = min(r[0] for r in older)
        report[sym] = f"+{n} ältere Tage ({src})"
    return report


def holdings_snapshot():
    """{key: (stück, einstand, last_changed-Datum)} aus input_number.depot_<key>_stuck/_einstand."""
    tpl = ("{% set ns = namespace(o=[]) %}{% for s in states.input_number "
           "if s.entity_id.startswith('input_number.depot_') and (s.entity_id.endswith('_stuck') "
           "or s.entity_id.endswith('_einstand')) %}{% set ns.o = ns.o + [[s.entity_id, s.state, "
           "s.last_changed.isoformat()]] %}{% endfor %}{{ ns.o | tojson }}")
    res = ha._req(f"{ha.CORE}/template", {"template": tpl})
    if isinstance(res, str):
        res = json.loads(res)
    out = {}
    for eid, val, changed in res:
        m = re.match(r"input_number\.depot_(.+)_(stuck|einstand)$", eid)
        if not m:
            continue
        key, kind = m.group(1), m.group(2)
        v = num(val)
        if v is None:
            continue
        cd = datetime.fromisoformat(changed).astimezone().date().isoformat()
        e = out.setdefault(key, {"stueck": None, "einstand": None, "datum": cd})
        e["stueck" if kind == "stuck" else "einstand"] = v
        e["datum"] = max(e["datum"], cd)
    return {k: v for k, v in out.items() if v["stueck"] is not None and v["einstand"] is not None}


def update_holdings(d, snap, keys):
    """Neue Bestände mit dem letzten gespeicherten vergleichen; Änderungen als Buchung festhalten."""
    new = []
    for key in keys:
        s = snap.get(key)
        if not s:
            continue
        hist = d["bestand"].setdefault(key, [])
        last = hist[-1] if hist else None
        if last and abs(last[1] - s["stueck"]) < 1e-6 and abs(last[2] - s["einstand"]) < 0.005:
            continue
        day = s["datum"]
        if last:
            if day <= last[0]:
                day = date.today().isoformat()
            ds, de_ = round(s["stueck"] - last[1], 6), round(s["einstand"] - last[2], 2)
            d["buchungen"].append([day, key, ds, de_, "erkannt"])
            new.append(f"{key}: {ds:+g} Stück, {de_:+.2f} € am {day}")
        hist.append([day if last else date.today().isoformat(), s["stueck"], round(s["einstand"], 2)])
    return new


def check_local_url():
    """Ist /local/ erreichbar? (Nur wenn der Ordner www beim HA-Start existierte.) Gibt (ok, Info) zurück."""
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE   # nur interne Erreichbarkeitsprüfung, es werden keine Daten gesendet
    errs = []
    for url in ("http://homeassistant:8123/local/depot-daten/verlauf.json",
                "https://homeassistant:8123/local/depot-daten/verlauf.json"):
        try:
            with urllib.request.urlopen(url, timeout=10, context=ctx if url.startswith("https") else None) as r:
                if r.status == 200:
                    return True, url.split(":")[0]
                errs.append(f"{url.split(':')[0]}: HTTP {r.status}")
        except urllib.error.HTTPError as e:
            errs.append(f"{url.split(':')[0]}: HTTP {e.code}")
        except Exception as e:
            errs.append(f"{url.split(':')[0]}: {type(e).__name__}")
    return False, "; ".join(errs)
