"""Eulerpool-Abrufe mit Zähler. Der Schlüssel taucht nie im Protokoll oder in Fehlertexten auf."""

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.eulerpool.com/api/1/"
log = logging.getLogger("depot_daten.eulerpool")


class Eulerpool:
    def __init__(self, token, usage):
        self.token = token
        self.usage = usage          # Usage-Objekt (zählt jeden Abruf)
        self.rate = {}              # zuletzt gesehene X-RateLimit-Header
        self._last = 0.0

    def get(self, path, **params):
        """GET; gibt (status, data) zurück. data ist None bei Fehler oder kaputtem JSON."""
        # höchstens ~4 Abrufe pro Sekunde (kostenlos erlaubt: 5)
        wait = 0.25 - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        params["token"] = self.token
        sep = "&" if "?" in path else "?"
        url = BASE + path + sep + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": "ha-depot-daten/0.2.1"})
        status, body, headers = 0, b"", {}
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=40) as r:
                    status, body, headers = r.status, r.read(), dict(r.headers)
            except urllib.error.HTTPError as e:
                status, body, headers = e.code, (e.read() or b""), dict(e.headers or {})
            except Exception as e:  # Netz, Zeitüberschreitung
                msg = str(e).replace(self.token, "***")
                log.warning("%s: %s", path.split("?")[0], msg)
                status = 0
            if status in (429, 500, 502, 503, 504, 0) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            break
        self._headers(headers)
        # Eulerpool zählt nur erfolgreiche Abrufe; wir zählen alles mit Antwort < 400 + 429
        self.usage.add(counted=status and status < 400)
        if status != 200:
            if status not in (404,):
                log.info("%s → HTTP %s", path.split("?")[0], status)
            return status, None
        try:
            return status, json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            return status, None

    def _headers(self, h):
        low = {k.lower(): v for k, v in (h or {}).items()}
        for key in ("x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset"):
            if key in low:
                self.rate[key.replace("x-ratelimit-", "")] = low[key]
        if "x-ratelimit-remaining" in low:
            self.usage.rate_update(low.get("x-ratelimit-limit"), low.get("x-ratelimit-remaining"))
