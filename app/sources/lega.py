"""Fonte dati Lega Serie A ufficiale (api.legaseriea.it + legaseriea.it).

Priorità Serie A only: se disponibile fornisce classifica/risultati/partite
ufficiali. Se l'API cambia o risponde 404, ritorna None e il facade
passa a ESPN (fallback a catena).
"""
import logging
import time

import config
from app.core.http import HTTPClient
from app.core.models import Fixture, OddsPick

log = logging.getLogger("lega")

# API nuove (2024+): il sito usa api.legaseriea.it/v2, le vecchie /api/season/*
# sono 404. Proviamo entrambe con fallback.
_LEGA_API = "https://api.legaseriea.it"
_OLD_ROOT = "https://www.legaseriea.it"


class LegaClient:
    def __init__(self):
        self.http = HTTPClient(base=_LEGA_API, tor_mode="never", delay=0.6)
        self.http_old = HTTPClient(base=_OLD_ROOT, tor_mode="never", delay=0.6)

    def resolve_season(self):
        # Lega non espone season/list stabile -> usiamo anno corrente come compat
        year = time.gmtime().tm_year
        # prova a validare una classifica per l'anno
        test = self.standings(f"{year}-{str(year+1)[-2:]}")
        if test:
            return {"id": f"{year}-{str(year+1)[-2:]}", "name": "Serie A", "source": "lega"}
        return {"id": f"{year}-{str(year+1)[-2:]}", "name": "Serie A", "source": "lega"}

    def standings(self, season_id=None):
        # Prova nuova API v2, poi vecchia Classificacompleta
        candidates = [
            f"/v2/competitions/SA/standings?season={season_id or ''}",
            f"/api/stats/Classificacompleta?CAMPIONATO=A&STAGIONE={season_id or '2024-25'}&TURNO=UNICO&GIRONE=UNI",
        ]
        for path in candidates:
            data = (self.http.get(path) if path.startswith("/v2") else self.http_old.get(path))
            if data:
                # normalizza se troviamo array di team
                try:
                    if isinstance(data, dict) and "standings" in data:
                        return data["standings"]
                    if isinstance(data, list) and data and "team" in str(data[0]).lower():
                        return data
                except:
                    pass
        return None

    def next_fixtures(self, season_id, days=10):
        # Non ancora mappato stabile -> lascia a ESPN/Sofascore via fallback
        return None

    def season_results(self, season_id, max_rounds=99):
        return None

    def event_detail(self, event_id):
        return None

    def odds_to_picks(self, event_id, source="lega"):
        return None

    def team_events(self, team_id, max_events=40):
        return None

    def live_events(self):
        return None

    def build_fixture(self, row, season_id):
        return None
