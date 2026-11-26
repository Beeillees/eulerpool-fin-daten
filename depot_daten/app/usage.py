"""Zählt Eulerpool-Abrufe pro Tag und Monat und merkt sich das über Neustarts."""

import json
from datetime import datetime
from pathlib import Path

FILE = Path("/data/usage.json")


class Usage:
    def __init__(self, path=FILE):
        self.path = path
        try:
            self.d = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.d = {}
        self._roll()

    def _roll(self):
        now = datetime.now()
        month, day = now.strftime("%Y-%m"), now.strftime("%Y-%m-%d")
        if self.d.get("month") != month:
            if self.d.get("month"):
                hist = self.d.setdefault("history", {})
                hist[self.d["month"]] = self.d.get("month_calls", 0)
                for k in sorted(hist)[:-12]:
                    del hist[k]
            self.d.update(month=month, month_calls=0)
        if self.d.get("day") != day:
            self.d.update(day=day, day_calls=0)

    def add(self, counted=True):
        self._roll()
        self.d["month_calls"] = self.d.get("month_calls", 0) + (1 if counted else 0)
        self.d["day_calls"] = self.d.get("day_calls", 0) + (1 if counted else 0)
        self.d["total_calls"] = self.d.get("total_calls", 0) + 1

    def save(self):
        try:
            self.path.write_text(json.dumps(self.d))
        except OSError:
            pass

    @property
    def month(self):
        self._roll()
        return self.d.get("month_calls", 0)

    @property
    def today(self):
        self._roll()
        return self.d.get("day_calls", 0)

    @property
    def history(self):
        return dict(self.d.get("history", {}))

    def get(self, key, default=None):
        return self.d.get(key, default)

    def set(self, key, value):
        self.d[key] = value
