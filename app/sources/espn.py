"""Fonte dati ESPN (API pubblica, senza chiave).

Copre: stagione, classifica, risultati, prossime partite, partite live.
Non fornisce quote 1X2 (le prende Sofascore) né le analisi profonde.
Usata come fallback quando Sofascore e' bloccato (es. IP datacenter/Tor).
"""
import logging
import time
from datetime import datetime, timedelta, timezone

import config
from app.core.http import HTTPClient
from app.core.models import Fixture

log = logging.getLogger("espn")

_SB = "https://site.api.espn.com/apis/site/v2/sports/soccer/ita.1"
_WEB = "https://site.web.api.espn.com/apis/v2/sports/soccer/ita.1"
_WINDOW_DAYS = 14  # limite del range di date di scoreboard


def _epoch(iso):
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except (ValueError, AttributeError):
        return 0


def _date(days=0):
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y%m%d")


def _chunks(start_days, end_days):
    for d0 in range(start_days, end_days, _WINDOW_DAYS):
        yield _date(d0), _date(min(d0 + _WINDOW_DAYS - 1, end_days))


def _status_name(state):
    s = state or ""
    if "FULL_TIME" in s or s in ("post", "postp"):
        return "finished"
    if state in ("in", "pre") and "PRE" in s:
        return "notstarted"
    if s in ("in", "pre") or "IN_PROGRESS" in s or "PAUSED" in s or "HALFTIME" in s:
        return "inprogress" if s != "pre" else "notstarted"
    if "SCHEDULED" in s or "PRE" in s:
        return "notstarted"
    if "POSTPONED" in s:
        return "postponed"
    if "CANCELLED" in s:
        return "cancelled"
    return "notstarted"


class EspnClient:
    def __init__(self):
        self.http = HTTPClient(base=_SB, tor_mode="never", delay=0.3)
        self.web = HTTPClient(base=_WEB, tor_mode="never", delay=0.3)
        self._results_cache = (0.0, [])

    # ------------------------------------------------------------- stagione
    def resolve_season(self):
        return {"id": "ita.1", "name": "Serie A", "source": "espn"}

    def standings(self, season_id=None):
        data = self.web.get("/standings")
        if not data:
            return []
        rows = []
        for child in data.get("children", []) or []:
            for entry in (child.get("standings", {}) or {}).get("entries", []) or []:
                team = entry.get("team") or {}
                stats = {s.get("name"): s.get("value")
                         for s in entry.get("stats", []) or []}
                rows.append({
                    "position": (entry.get("note") or {}).get("rank",
                                                              len(rows) + 1),
                    "team_id": team.get("id"),
                    "name": team.get("displayName"),
                    "points": stats.get("points"),
                    "played": stats.get("gamesPlayed"),
                    "wins": stats.get("wins"),
                    "draws": stats.get("ties"),
                    "losses": stats.get("losses"),
                    "gf": stats.get("pointsFor"),
                    "ga": stats.get("pointsAgainst"),
                })
        return rows

    # ------------------------------------------------------------- eventi
    def _events(self, start_days, end_days, limit=100):
        out = []
        for d0, d1 in _chunks(start_days, end_days):
            data = self.http.get(
                "/scoreboard", params={"dates": f"{d0}-{d1}", "limit": limit})
            if not data:
                continue
            for e in data.get("events", []) or []:
                comp = (e.get("competitions") or [{}])[0]
                if not comp.get("competitors"):
                    continue
                out.append(comp)
        return out

    def next_fixtures(self, season_id, days=10):
        rows = []
        now = time.time()
        for comp in self._events(0, days):
            ts = _epoch(comp.get("date") or comp.get("startDate"))
            if ts < now - 3600 or ts > now + days * 86400:
                continue
            home, away = comp.get("competitors") or []
            if not home or not away:
                continue
            rows.append(self._row(comp, ts))
        rows.sort(key=lambda x: x[5])
        return rows

    def _row(self, comp, ts):
        home, away = comp.get("competitors") or []
        by = {c.get("homeAway"): (c.get("team") or {}) for c in (home, away)}
        ht, at = by.get("home") or {}, by.get("away") or {}
        return (comp.get("id"), ht.get("displayName"), at.get("displayName"),
                ht.get("id"), at.get("id"), ts, None)

    def season_results(self, season_id, max_rounds=99):
        now = time.time()
        if now - self._results_cache[0] < 600:
            return self._results_cache[1]
        by_round = {}
        for comp in self._events(-180, 0, limit=70):
            st = self._status_name((comp.get("status") or {}).get("type", {}).get("name"))
            if st != "finished":
                continue
            home, away = comp.get("competitors") or []
            if not home or not away:
                continue
            hs = (home or {}).get("score")
            as_ = (away or {}).get("score")
            if hs is None or as_ is None:
                continue
            by_round.setdefault(None, []).append({
                "id": comp.get("id"),
                "home": (home.get("team") or {}).get("displayName"),
                "away": (away.get("team") or {}).get("displayName"),
                "home_id": (home.get("team") or {}).get("id"),
                "away_id": (away.get("team") or {}).get("id"),
                "score": f"{hs}-{as_}", "hs": hs, "as": as_,
                "start_ts": _epoch(comp.get("date") or comp.get("startDate")),
            })
        rounds = [{"round": r, "matches": ms}
                  for r, ms in sorted(by_round.items(), key=lambda kv: (kv[0] or 0))]
        self._results_cache = (now, rounds)
        return rounds

    def event_detail(self, event_id):
        data = self.http.get("/summary", params={"event": event_id})
        if not data:
            return None
        comp = ((data.get("header", {}) or {}).get("competitions") or [{}])[0]
        home, away = comp.get("competitors") or []
        if not home or not away:
            return None
        s = (comp.get("status") or {}).get("type", {}) or {}
        return {
            "id": comp.get("id"),
            "home": (home.get("team") or {}).get("displayName"),
            "away": (away.get("team") or {}).get("displayName"),
            "home_id": (home.get("team") or {}).get("id"),
            "away_id": (away.get("team") or {}).get("id"),
            "start_ts": _epoch(comp.get("date") or comp.get("startDate")),
            "round": None,
            "venue": (comp.get("venue") or {}).get("fullName") or "",
            "status": self._status_name(s.get("name")),
            "home_score": comp.get("competitors", [{}])[0].get("score"),
            "away_score": comp.get("competitors", [{}])[1].get("score"),
            "referee": {},
        }

    def live_events(self):
        out = []
        for comp in self._events(0, 0):
            home, away = comp.get("competitors") or []
            if not home or not away:
                continue
            status = (comp.get("status") or {}).get("type", {}) or {}
            period = status.get("detail") or status.get("name") or ""
            out.append({
                "id": comp.get("id"),
                "home": (home.get("team") or {}).get("displayName"),
                "away": (away.get("team") or {}).get("displayName"),
                "home_id": (home.get("team") or {}).get("id"),
                "away_id": (away.get("team") or {}).get("id"),
                "hs": home.get("score"), "as": away.get("score"),
                "status": self._status_name(status.get("name")),
                "period": period,
                "minute": None,
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