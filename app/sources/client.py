"""Facade multi-fonte: prova le fonti in DATA_SOURCE_ORDER (fallback a catena).

Fonte            stagione classifica risultati partite live quote 1X2 analisi
sofascore           si       si        si       si    si     si        si
espn                si       si        si       si    si(punteggi) si(1X2) no

Le "analisi" (lineups, incidenti, statistiche, arbitri, h2h, forma, xG…)
riguardano soltanto l'engine sofascore: se nelle fonti non c'e', quei metodi
rispondono con un default vuoto e le feature affinate degradano.
"""
import logging

import config
from app.sources import espn, sofascore

log = logging.getLogger("sources")

# Capacita' coperte da piu' fonti -> fallback a catena.
_CORE = {
    "resolve_season", "standings", "next_fixtures", "build_fixture",
    "event_detail", "odds_to_picks", "event_odds", "season_results",
    "live_events",
}
# Solo il motore sofascore (lineups/stat/info profondi) li fornisce.
_ANALYTICS_EMPTY = {
    "lineups": None, "probable_xi": None, "statistics": {},
    "team_injuries": [], "team_events": [], "referee_events": [],
    "collect_past_matches": [], "stats_for_events": {},
    "incidents_for_events": {}, "incidents": [],
}


class FootballClient:
    def __init__(self):
        factories = {
            "sofascore": sofascore.SofascoreClient,
            "espn": espn.EspnClient,
        }
        chosen = [n for n in config.DATA_SOURCE_ORDER if n in factories]
        self.sources = [factories[n]() for n in chosen]
        self._sofascore = next(
            (s for s in self.sources if isinstance(s, sofascore.SofascoreClient)),
            None)
        if not self.sources:
            log.error("nessuna fonte in DATA_SOURCE_ORDER=%s", config.DATA_SOURCE_ORDER)

    def _pick(self, name, *args, **kwargs):
        last = None
        for s in self.sources:
            fn = getattr(s, name, None)
            if fn is None:
                continue
            try:
                value = fn(*args, **kwargs)
            except Exception as e:
                log.warning("%s: fonte %s risponde con errore: %s", name, s.__class__.__name__, e)
                continue
            if value:
                return value
            if value is not None:
                last = value
            log.debug("%s: fonte %s risposta vuota, provo la successiva", name, s.__class__.__name__)
        return last

    def _cached(self, key, generator):
        engine = self._sofascore
        if engine is None:
            return None
        return engine._cached(key, generator)

    def _ttl_cached(self, key, ttl, generator):
        engine = self._sofascore
        if engine is None:
            return None
        return engine._ttl_cached(key, ttl, generator)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name in _CORE:
            return lambda *args, **kwargs: self._pick(name, *args, **kwargs)
        if name in _ANALYTICS_EMPTY:
            engine = self._sofascore
            if engine is None:
                log.warning("%s: motore sofascore assente tra le fonti", name)
                return lambda *args, **kwargs: _ANALYTICS_EMPTY[name]
            return getattr(engine, name)
        raise AttributeError(name)