"""Fonte dati ESPN (API pubblica, senza chiave).

Covers: stagione, classifica, risultati, prossime partite, partite live,
quote 1X2 (Bet365, se presenti nei dati core API).

Usa due domini ESPN:
- sports.core.api.espn.com  -> eventi, quote, live, risultati (risponde anche
  da IP datacenter/exit perche' e' l'API delle app ESPN)
- site.web.api.espn.com     -> classifica (host bloccato? no, funziona)
"""
import logging
import time
from datetime import datetime, timedelta, timezone

import config
from app.core.http import HTTPClient
from app.core.models import Fixture, OddsPick

log = logging.getLogger("espn")

_CORE = "https://sports.core.api.espn.com/v2/sports/soccer/leagues/ita.1"
_WEB = "https://site.web.api.espn.com/apis/v2/sports/soccer/ita.1"


def _epoch(iso):
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except (ValueError, AttributeError):
        return 0


def _date(days=0):
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y%m%d")


def _status_name(state, description=""):
    s = (state or "").upper()
    if "FULL" in s or "FINAL" in s or s == "POST":
        return "finished"
    if "LIVE" in s or "IN_PROGRESS" in s or "HALFTIME" in s or s == "IN":
        return "inprogress"
    if "POSTPONED" in s:
        return "postponed"
    if "CANCEL" in s:
        return "cancelled"
    return "notstarted"


class EspnClient:
    def __init__(self):
        self.http = HTTPClient(base=_CORE, tor_mode="never", delay=0.3)
        self.web = HTTPClient(base=_WEB, tor_mode="never", delay=0.3)
        self.sched = HTTPClient(
            base="https://site.web.api.espn.com/apis/site/v2/sports/soccer/ita.1",
            tor_mode="never", delay=0.3)
        self._results_cache = (0.0, [])
        self._teams_cache = {}  # team_id -> displayName
        self._events_by_id = {}  # event_id -> dict(comp, odds_1x2)

    # ------------------------------------------------------------- stagione
    def resolve_season(self):
        # id = anno corrente: i team schedule di ESPN portano season.year
        return {"id": "2026", "name": "Serie A", "source": "espn"}

    def _team_name(self, team_id):
        if team_id not in self._teams_cache:
            data = self.http.get(f"/seasons/2026/teams/{team_id}")
            self._teams_cache[team_id] = (data or {}).get("displayName") or str(team_id)
        return self._teams_cache[team_id]

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
    def _events(self, start_days, end_days, limit=100, with_odds=True):
        """Eventi in un range di giorni, via core.api (ref navigation)."""
        out = []
        d0, d1 = _date(start_days), _date(end_days)
        data = self.http.get("/events", params={
            "limit": limit, "dates": f"{d0}-{d1}"})
        if not data:
            return out
        for item in data.get("items", []) or []:
            ref = (item.get("$ref") or item.get("ref") or "")
            event_id = ref.rstrip("?lang=en&region=us").split("/events/")[-1]
            if not event_id or event_id.startswith("seasons"):
                continue
            comp = self._competition(event_id, with_odds=with_odds)
            if comp:
                out.append(comp)
                self._events_by_id[event_id] = comp
        return out

    def _competition(self, event_id, with_odds=True):
        data = self.http.get(f"/events/{event_id}/competitions/{event_id}")
        if not data:
            return None
        comp = {"id": event_id,
                "date": data.get("date"),
                "status": self._status(event_id),
                "venue": (data.get("venue") or {}).get("fullName"),
                "competitors": data.get("competitors") or []}
        # punteggi via ref
        for c in comp["competitors"]:
            cid = c.get("id")
            c["score"] = self._score(event_id, cid) or 0
        # quote 1X2 Bet365
        comp["odds_raw"] = self._odds_items(event_id) if with_odds else []
        comp["odds"] = self._picks_from_odds(comp["odds_raw"])
        return comp

    def _status(self, event_id):
        data = self.http.get(
            f"/events/{event_id}/competitions/{event_id}/status")
        return (data or {}).get("type") or {}

    def _score(self, event_id, comp_id):
        data = self.http.get(
            f"/events/{event_id}/competitions/{event_id}/competitors/{comp_id}/score")
        return (data or {}).get("value")

    def _odds_items(self, event_id):
        data = self.http.get(
            f"/events/{event_id}/competitions/{event_id}/odds?limit=50")
        return (data or {}).get("items") or []

    @staticmethod
    def _picks_from_odds(items):
        for item in items:
            if (item.get("provider") or {}).get("name") != "Bet 365":
                continue
            home = (item.get("homeTeamOdds") or {}).get("odds", {}).get("value")
            draw = (item.get("drawOdds") or {}).get("value")
            away = (item.get("awayTeamOdds") or {}).get("odds", {}).get("value")
            picks = []
            for value, pick in [(home, "1"), (draw, "X"), (away, "2")]:
                try:
                    dec = float(value)
                except (TypeError, ValueError):
                    continue
                picks.append(OddsPick(source="espn", market="Full time",
                                      pick=pick, odds=round(dec, 2)))
            return picks
        return []

    def odds_to_picks(self, event_id, source="espn"):
        comp = self._events_by_id.get(event_id) or {}
        picks = comp.get("odds")
        if picks:
            return picks
        return self._picks_from_odds(comp.get("odds_raw") or [])

    def _teams(self, comp):
        home, away = comp.get("competitors") or []
        if not home or not away:
            return None, None
        by = {c.get("homeAway"): c for c in (home, away)}
        ht, at = by.get("home") or {}, by.get("away") or {}
        return ht, at

    def _row(self, comp, ts=None):
        ht, at = self._teams(comp)
        if not ht or not at:
            return None
        hid, aid = ht.get("id"), at.get("id")
        return (comp.get("id"), self._team_name(hid), self._team_name(aid),
                hid, aid, ts if ts is not None else _epoch(comp.get("date")), None)

    def next_fixtures(self, season_id, days=10):
        rows = []
        now = time.time()
        for comp in self._events(0, days):
            ts = _epoch(comp.get("date"))
            if ts < now - 3600 or ts > now + days * 86400:
                continue
            row = self._row(comp, ts)
            if row:
                rows.append(row)
        rows.sort(key=lambda x: x[5])
        return rows

    def season_results(self, season_id, max_rounds=99):
        now = time.time()
        if now - self._results_cache[0] < 600:
            return self._results_cache[1]
        matches = []
        for comp in self._events(-14, 0, with_odds=False):
            st = _status_name((comp.get("status") or {}).get("name"))
            if st != "finished":
                continue
            ht, at = self._teams(comp)
            if not ht or not at:
                continue
            hs, as_ = ht.get("score"), at.get("score")
            if hs is None or as_ is None:
                continue
            matches.append({
                "id": comp.get("id"),
                "home": self._team_name(ht.get("id")),
                "away": self._team_name(at.get("id")),
                "home_id": ht.get("id"), "away_id": at.get("id"),
                "score": f"{int(hs)}-{int(as_)}", "hs": int(hs), "as": int(as_),
                "start_ts": _epoch(comp.get("date")),
            })
        rounds = [{"round": None, "matches": matches}]
        self._results_cache = (now, rounds)
        return rounds

    def event_detail(self, event_id):
        comp = self._events_by_id.get(event_id) or self._competition(event_id)
        if not comp:
            return None
        ht, at = self._teams(comp)
        if not ht or not at:
            return None
        s = comp.get("status") or {}
        return {
            "id": comp.get("id"),
            "home": self._team_name(ht.get("id")),
            "away": self._team_name(at.get("id")),
            "home_id": ht.get("id"), "away_id": at.get("id"),
            "start_ts": _epoch(comp.get("date")),
            "round": None,
            "venue": comp.get("venue") or "",
            "status": _status_name(s.get("name")),
            "home_score": ht.get("score"),
            "away_score": at.get("score"),
            "referee": {},
        }

    def team_events(self, team_id, max_events=40):
        """Cronologia partite della squadra dal calendario pubblico ESPN
        (stessi eventi dei risultati: alimenta forma e h2h senza Sofascore)."""
        data = self.sched.get(f"/teams/{team_id}/schedule")
        if not data:
            return []
        events = data.get("events") or []
        out = []
        for e in events:
            comps = ((e.get("competitions") or [{}])[0]).get("competitors") or []
            by_side = {c.get("homeAway"): c for c in comps}
            h, a = by_side.get("home"), by_side.get("away")
            if not h or not a:
                continue
            ht, at = h.get("team") or {}, a.get("team") or {}
            status = (e.get("competitions") or [{}])[0].get("status") or {}
            finished = (status.get("type") or {}).get("state") == "post"
            hscore = (h.get("score") or {}).get("displayValue")
            ascore = (a.get("score") or {}).get("displayValue")

            def _int(v):
                try:
                    return int(float(v))
                except (TypeError, ValueError):
                    return None

            out.append({
                "id": e.get("id"),
                "home": ht.get("displayName") or str(ht.get("id")),
                "away": at.get("displayName") or str(at.get("id")),
                "home_id": ht.get("id"), "away_id": at.get("id"),
                "finished": finished,
                "start_ts": _epoch(e.get("date")),
                "season_id": str((e.get("season") or {}).get("year")),
                "home_score": _int(hscore),
                "away_score": _int(ascore),
            })
        out.sort(key=lambda x: x["start_ts"] or 0, reverse=True)
        return out[:max_events]

    def live_events(self):
        out = []
        for comp in self._events(0, 0):
            st = _status_name((comp.get("status") or {}).get("name"))
            if st != "inprogress":
                continue
            ht, at = self._teams(comp)
            if not ht or not at:
                continue
            out.append({
                "id": comp.get("id"),
                "home": self._team_name(ht.get("id")),
                "away": self._team_name(at.get("id")),
                "home_id": ht.get("id"), "away_id": at.get("id"),
                "hs": ht.get("score"), "as": at.get("score"),
                "status": st,
                "period": (comp.get("status") or {}).get("shortDetail") or st,
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
        fx.odds = self.odds_to_picks(row[0])
        return fx