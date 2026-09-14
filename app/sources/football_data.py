"""Fonte dati football-data.org v4 (Serie A = competition SA).

Richiede FOOTBALL_DATA_KEY (header X-Auth-Token).
Copre: stagione, classifica, risultati, prossime partite.
Non fornisce quote, h2h né punteggi live/realtime affidabili.
"""
import logging
import time
from datetime import datetime, timezone

import config
from app.core.http import HTTPClient
from app.core.models import Fixture

log = logging.getLogger("football_data")


def _epoch(iso):
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except (ValueError, AttributeError):
        return 0


class FootballDataClient:
    def __init__(self):
        self.code = config.FOOTBALL_DATA_CODE
        self.http = HTTPClient(base="https://api.football-data.org/v4",
                               tor_mode="never", delay=0.5)

    @property
    def active(self):
        return bool(config.FOOTBALL_DATA_KEY)

    def _headers(self):
        return {"X-Auth-Token": config.FOOTBALL_DATA_KEY}

    def _get(self, path, params=None):
        if not self.active:
            return None
        return self.http.get(path, params=params or {}, headers=self._headers())

    # ------------------------------------------------------------- stagione
    def resolve_season(self):
        return {"id": self.code, "name": "Serie A", "source": "football_data"}

    def standings(self, season_id=None):
        data = self._get(f"/competitions/{self.code}/standings")
        if not data or not data.get("standings"):
            return []
        rows = []
        for t in (data["standings"][0].get("table") or []):
            team = t.get("team") or {}
            rows.append({
                "position": t.get("position"),
                "team_id": team.get("id"),
                "name": team.get("shortName") or team.get("name"),
                "points": t.get("points"),
                "played": t.get("playedGames"),
                "wins": t.get("won"),
                "draws": t.get("drawn"),
                "losses": t.get("lost"),
                "gf": t.get("goalsFor"),
                "ga": t.get("goalsAgainst"),
            })
        return rows

    def _matches(self, params):
        data = self._get(f"/competitions/{self.code}/matches", params)
        out = []
        for m in ((data or {}).get("matches") or []):
            score = m.get("score") or {}
            ft = score.get("fullTime") or score.get("regularTime") or {}
            out.append({
                "id": m.get("id"),
                "home": (m.get("homeTeam") or {}).get("name"),
                "away": (m.get("awayTeam") or {}).get("name"),
                "home_id": (m.get("homeTeam") or {}).get("id"),
                "away_id": (m.get("awayTeam") or {}).get("id"),
                "ts": _epoch(m.get("utcDate")),
                "round": m.get("matchday"),
                "status": m.get("status", "SCHEDULED").upper(),
                "hs": ft.get("home"), "as": ft.get("away"),
            })
        return out

    def next_fixtures(self, season_id, days=10):
        now = time.time()
        rows = []
        for m in self._matches({"status": "SCHEDULED", "limit": 100}):
            if m["ts"] and now <= m["ts"] <= now + days * 86400:
                rows.append((m["id"], m["home"], m["away"], m["home_id"],
                             m["away_id"], m["ts"], m["round"]))
        rows.sort(key=lambda x: x[5])
        return rows

    def season_results(self, season_id, max_rounds=99):
        by_round = {}
        for m in self._matches({"status": "FINISHED", "limit": 250}):
            if m["hs"] is None:
                continue
            by_round.setdefault(m["round"], []).append({
                "id": m["id"], "home": m["home"], "away": m["away"],
                "home_id": m["home_id"], "away_id": m["away_id"],
                "score": f"{m['hs']}-{m['as']}", "hs": m["hs"], "as": m["as"],
                "start_ts": m["ts"],
            })
        rounds = [{"round": rnd, "matches": ms}
                  for rnd, ms in sorted(by_round.items())[-max_rounds:]]
        return rounds

    def event_detail(self, event_id):
        data = self._get(f"/matches/{event_id}")
        if not data:
            return None
        score = data.get("score") or {}
        ft = score.get("fullTime") or {}
        return {
            "id": event_id,
            "home": (data.get("homeTeam") or {}).get("name"),
            "away": (data.get("awayTeam") or {}).get("name"),
            "home_id": (data.get("homeTeam") or {}).get("id"),
            "away_id": (data.get("awayTeam") or {}).get("id"),
            "start_ts": _epoch(data.get("utcDate")),
            "round": data.get("matchday"),
            "venue": "",
            "status": "finished" if (data.get("status") or "").upper() == "FINISHED"
                      else "notstarted",
            "home_score": ft.get("home"),
            "away_score": ft.get("away"),
            "referee": {},
        }

    def live_events(self):
        out = []
        for status in ("IN_PLAY", "PAUSED"):
            for m in self._matches({"status": status}):
                out.append({
                    "id": m["id"], "home": m["home"], "away": m["away"],
                    "home_id": m["home_id"], "away_id": m["away_id"],
                    "hs": m["hs"], "as": m["as"], "status": "inprogress",
                    "period": status, "minute": None,
                })
        return out

    def build_fixture(self, row, season_id):
        detail = self.event_detail(row[0]) or {}
        fx = Fixture(
            id=row[0], home=detail.get("home", row[1]),
            away=detail.get("away", row[2]), home_id=row[3], away_id=row[4],
            start_ts=row[5], round=row[6] or detail.get("round"),
            venue=detail.get("venue", ""), status=detail.get("status", ""),
            referee=detail.get("referee", {}),
        )
        fx.odds = []
        return fx