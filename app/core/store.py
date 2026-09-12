"""Persistenza dello stato su JSON in modo atomico (disco o Redis remoto)."""
import json
import logging
import threading
import time

from app.core import kv

log = logging.getLogger("store")


class Store:
    def __init__(self, path=None):
        self.path = path
        self._lock = threading.RLock()
        self.data = {"version": 1, "updated": 0, "season": None,
                     "standings": [], "fixtures": [], "value_flags": [],
                     "sources": {}, "matches_played": {}, "tracking": {},
                     "calibration": {}}

    def load(self):
        with self._lock:
            loaded = kv.read_json("state.json")
            if loaded:
                self.data.update(loaded)
                log.info("Stato caricato (disco/Redis)")
        return self.data

    def save(self):
        with self._lock:
            self.data["updated"] = int(time.time())
            kv.write_json("state.json", self.data)

    def get(self, key, default=None):
        with self._lock:
            return self.data.get(key, default)

    def set(self, key, value):
        with self._lock:
            self.data[key] = value