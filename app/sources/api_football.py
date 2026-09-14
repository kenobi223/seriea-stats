"""Fonte dati api-football.com v3 (Serie A = league 135).

Richiede API_FOOTBALL_KEY (dashboard ufficiale -> header x-apisports-key,
oppure account RapidAPI con API_FOOTBALL_PROVIDER=rapidapi).
Copre: stagione, classifica, risultati, prossime partite, live.
Le quote 1X2 NON sono ancora mappate dal questo adapter.
"""
import logging
import time
from datetime import datetime

import config
from app.core.http import HTTPClient
from app.core.models import Fixture

log = logging.getLogger("api_football")

_ST = {
    "FT": "finished", "AET": "finished", "PEN": "finished",
    "1H": "inprogress", "2H": "inprogress", "HT": "inprogress",
    "ET": "inprogress", "BT": "inprogress", "LIVE": "inprogress",
    "NS": "notstarted", "TIMED": "notstarted", "TBD": "notstarted",
    "POSTP": "postponed", "CANC": "cancelled", "SUSP": "inprogress",
    "INT": "inprogress",
}


def _epoch(iso):
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except (ValueError, AttributeError):
        return 0


def _round_num(round_label):
    """'Regular Season - 7' / 'Giornata 7' / 'Matchday 7' -> 7."""
    if not round_label:
        return None
    for token in reversed(round_label.split()):
        if token.isdigit():
            return int(token)
    return None


class ApiFootballClient:
    def __init__(self):
        self.key = config.API_FOOTBALL_KEY
        self.http = HTTPClient(base="https://v3.football.api-sports.io",
                               tor_mode="never", delay=0.5)

    @property
    def active(self):
        return bool(self.key)

    def _headers(self):
        if config.API_FOOTBALL_PROVIDER == "rapidapi":
            return {"x-rapidapi-key": self.key,
                    "x-rapidapi-host": "v3.football.api-sports.io"}
        return {"x-apisports-key": self.key}

    def _season(self):
        y = datetime.now().year
        return str(y if datetime.now().month >= 7 else y - 1)

    def _get(self, path, params=None):
        if not self.active:
            return None
        return self.http.get(path, params=params or {}, headers=self._headers())

    # ------------------------------------------------------------- stagione
    def resolve_season(self):
        return {"id": self._season(), "name": "Serie A", "source": "api_football"}

    def standings(self, season_id=None):
        data = self._get("/standings",
                         {"league": config.API_FOOTBALL_LEAGUE, "season": self._season()})
        if not data or not data.get("response"):
            return []
        rows = []
        for t in (data["response"][0].get("league", {}).get("standings") or [None])[0] or []:
            team = t.get("team") or {}
            all_ = t.get("all") or {}
            goals = t.get("goals") or {}
            rows.append({
                "position": t.get("rank"),
                "team_id": team.get("id"),
                "name": team.get("name"),
                "points": t.get("points"),
                "played": all_.get("played"),
                "wins": all_.get("win"),
                "draws": all_.get("draw"),
                "losses": all_.get("lose"),
                "gf": goals.get("for"),
                "ga": goals.get("against"),
            })
        return rows

    def _fixture_rows(self, params):
        data = self._get("/fixtures", params)
        out = []
        for f in (data or {}).get("response", []) or []:
            fx = f.get("fixture") or {}
            teams = f.get("teams") or {}
            ht = teams.get("home") or {}
            at = teams.get("away") or {}
            out.append({
                "id": fx.get("id"),
                "home": ht.get("name"), "away": at.get("name"),
                "home_id": ht.get("id"), "away_id": at.get("id"),
                "ts": _epoch(fx.get("date")),
                "round": _round_num((f.get("league") or {}).get("round")),
                "status": _ST.get((fx.get("status") or {}).get("short"), "notstarted"),
                "hs": (f.get("goals") or {}).get("home"),
                "as": (f.get("goals") or {}).get("away"),
            })
        return out

    def next_fixtures(self, season_id, days=10):
        now = time.time()
        rows = []
        for r in self._fixture_rows({"league": config.API_FOOTBALL_LEAGUE,
                                     "season": self._season(), "next": 40}):
            if r["ts"] and now <= r["ts"] <= now + days * 86400:
                rows.append((r["id"], r["home"], r["away"], r["home_id"],
                             r["away_id"], r["ts"], r["round"]))
        rows.sort(key=lambda x: x[5])
        return rows

    def season_results(self, season_id, max_rounds=99):
        by_round = {}
        for r in self._fixture_rows({"league": config.API_FOOTBALL_LEAGUE,
                                     "season": self._season(), "status": "FT"}):
            if not r["id"]:
                continue
            by_round.setdefault(r["round"], []).append({
                "id": r["id"], "home": r["home"], "away": r["away"],
                "home_id": r["home_id"], "away_id": r["away_id"],
                "score": f"{r['hs']}-{r['as']}", "hs": r["hs"], "as": r["as"],
                "start_ts": r["ts"],
            })
        rounds = [{"round": rnd, "matches": ms}
                  for rnd, ms in sorted(by_round.items())[-max_rounds:]]
        return rounds

    def event_detail(self, event_id):
        data = self._get("/fixtures", {"id": event_id})
        items = (data or {}).get("response") or []
        if not items:
            return None
        f = items[0]
        fx = f.get("fixture") or {}
        teams = f.get("teams") or {}
        ht = teams.get("home") or {}
        at = teams.get("away") or {}
        return {
            "id": fx.get("id"),
            "home": ht.get("name"), "away": at.get("name"),
            "home_id": ht.get("id"), "away_id": at.get("id"),
            "start_ts": _epoch(fx.get("date")),
            "round": _round_num((f.get("league") or {}).get("round")),
            "venue": ((fx.get("venue") or {}).get("name")) or "",
            "status": _ST.get((fx.get("status") or {}).get("short"), "notstarted"),
            "home_score": (f.get("goals") or {}).get("home"),
            "away_score": (f.get("goals") or {}).get("away"),
            "referee": {},
        }

    def live_events(self):
        out = []
        for r in self._fixture_rows({"league": config.API_FOOTBALL_LEAGUE,
                                     "season": self._season(), "live": "all"}):
            out.append({
                "id": r["id"], "home": r["home"], "away": r["away"],
                "home_id": r["home_id"], "away_id": r["away_id"],
                "hs": r["hs"], "as": r["as"], "status": r["status"],
                "period": r["status"], "minute": None,
            })
        return [m for m in out if m["status"] == "inprogress"]

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