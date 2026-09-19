"""Client dati Sofascore (API pubblica, senza chiave).

Fornisce: stagione corrente, classifica, prossime partite, dettaglio
(arbitro), formazioni, statistiche (tiri in porta...), incidenti
(cartellini), cronologia squadre, infortuni e quote 1X2.
"""
import json
import logging
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
from app.core.http import HTTPClient
from app.core.models import Fixture, OddsPick

log = logging.getLogger("sofascore")

_MARKET_IDS = [1]  # una sola chiamata restituisce tutti i mercati


def _frac2dec(value):
    """Converte una frazione '23/20' in decimale 2.15."""
    try:
        if value is None:
            return None
        if "." in value:
            return float(value)
        a, b = value.split("/")
        return round(float(a) / float(b) + 1.0, 2)
    except (ValueError, ZeroDivisionError, AttributeError):
        return None


class SofascoreClient:
    def __init__(self):
        self.http = HTTPClient(base=config.SOFASCORE_BASE,
                               tor_mode=config.SOFASCORE_TOR_MODE)
        self.cache_dir = os.path.join(config.DATA_DIR, "cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._mem = threading.Lock()

    # ------------------------------------------------------------- utils
    def _ttl_cached(self, key, ttl, generator):
        """Cache generica su disco con TTL (secondi); generator -> valore JSON."""
        path = os.path.join(self.cache_dir, key + ".json")
        with self._mem:
            if os.path.exists(path):
                try:
                    with open(path, encoding="utf-8") as f:
                        blob = json.load(f)
                    if time.time() - (blob.get("t") or 0) < ttl:
                        return blob.get("d")
                except Exception:
                    pass
        val = generator()
        try:
            with self._mem:
                os.makedirs(self.cache_dir, exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump({"t": time.time(), "d": val}, f, ensure_ascii=False)
        except Exception as e:
            log.debug("ttl cache %s: %s", key, e)
        return val

    def _cached(self, key, generator):
        path = os.path.join(self.cache_dir, key + ".json")
        with self._mem:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass
        value = generator()
        if value is not None:
            with self._mem:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(value, f, ensure_ascii=False)
        return value

    # ------------------------------------------------------------- season
    def resolve_season(self):
        data = self.http.get("unique-tournament/23/seasons")
        if not data or "seasons" not in data:
            return None
        for s in data["seasons"]:
            if s.get("year", "").endswith(config.STATUS_SEASON_PREFIX) or \
                    s.get("year", "").replace("/", "") == config.STATUS_SEASON_PREFIX.replace("/", ""):
                return s
        return data["seasons"][0]

    def standings(self, season_id):
        data = self.http.get(f"unique-tournament/23/season/{season_id}/standings/total")
        if not data:
            return []
        groups = data.get("standings") or []
        if not groups:
            return []
        rows = []
        for r in groups[0].get("rows", []):
            team = r.get("team") or {}
            rows.append({
                "position": r.get("position"),
                "team_id": team.get("id"),
                "name": team.get("name"),
                "slug": team.get("slug"),
                "colors": team.get("teamColors"),
                "points": r.get("points"),
                "played": r.get("played") or r.get("matches"),
                "wins": r.get("wins"),
                "draws": r.get("draws"),
                "losses": r.get("losses"),
                "gf": r.get("scoresFor"),
                "ga": r.get("scoresAgainst"),
            })
        return rows

    def next_fixtures(self, season_id, days=10):
        """Prossime partite Serie A entro `days` giorni."""
        data = self.http.get(f"unique-tournament/23/season/{season_id}/events/next/0")
        if not data:
            return []
        import time as _t
        now = _t.time()
        limit = now + days * 86400
        out = []
        for e in data.get("events", []):
            ts = e.get("startTimestamp") or 0
            if ts > limit or ts < now - 3600:
                continue
            ht = e.get("homeTeam") or {}
            at = e.get("awayTeam") or {}
            ri = e.get("roundInfo") or {}
            out.append((e.get("id"), ht.get("name"), at.get("name"),
                        ht.get("id"), at.get("id"), ts, ri.get("round")))
        out.sort(key=lambda x: x[5])
        return out

    # ------------------------------------------------------------- singoli
    def event_detail(self, event_id):
        data = self.http.get(f"event/{event_id}")
        if not data:
            return None
        ev = data.get("event") or {}
        venue = (ev.get("venue") or {}).get("name") or ""
        referee = ev.get("referee") or {}
        home = ev.get("homeTeam") or {}
        away = ev.get("awayTeam") or {}
        ri = ev.get("roundInfo") or {}
        status = ev.get("status") or {}
        hs = ev.get("homeScore") or {}
        as_ = ev.get("awayScore") or {}
        return {
            "id": ev.get("id"),
            "home": home.get("name"),
            "away": away.get("name"),
            "home_id": home.get("id"),
            "away_id": away.get("id"),
            "start_ts": ev.get("startTimestamp"),
            "round": ri.get("round"),
            "venue": venue,
            "status": status.get("type"),
            "home_score": hs.get("current"),
            "away_score": as_.get("current"),
            "referee": {
                "id": referee.get("id"),
                "name": referee.get("name"),
                "games": referee.get("games"),
                "yellow": referee.get("yellowCards"),
                "red": referee.get("redCards"),
                "yred": referee.get("yellowRedCards"),
            },
        }

    def lineups(self, event_id):
        data = self.http.get(f"event/{event_id}/lineups")
        if not data:
            return None
        result = {"home": None, "away": None}

        def _player_entry(p):
            player = p.get("player") or {}
            st = p.get("statistics") or {}
            total = st.get("totalShots")
            off = st.get("shotOffTarget")
            sot = None
            if total is not None and off is not None:
                sot = max(0, int(total) - int(off))
            return {
                "name": player.get("name"),
                "id": player.get("id"),
                "position": p.get("position"),
                "substitute": p.get("substitute"),
                "shirt": p.get("shirtNumber"),
                "shots_on_target": sot,
                "saves": st.get("totalSaves") or st.get("total_saves"),
                "minutes": st.get("minutesPlayed"),
            }

        for side in ("home", "away"):
            block = data.get(side)
            if not block:
                continue
            players = [_player_entry(p) for p in block.get("players", [])]
            result[side] = {
                "confirmed": bool(block.get("confirmed")),
                "players": players,
                "formation": block.get("formation"),
            }
        return result

    def probable_xi(self, event_id, ttl=1800):
        """XI probabile di Sofascore per un evento imminente, con infortunati.

        Per gli eventi futuri Sofascore pubblica una formazione probabile
        (11 titolari + panchina) con `missingPlayers` per lato; a ridosso del
        calcio d'inizio diventa quella ufficiale (`confirmed`).
        """
        def _fetch():
            data = self.http.get(f"event/{event_id}/lineups")
            if not data:
                return None
            out = {"home": None, "away": None}
            for side in ("home", "away"):
                block = data.get(side)
                if not block:
                    continue
                players = []
                for p in block.get("players", []):
                    player = p.get("player") or {}
                    players.append({
                        "id": player.get("id"),
                        "name": player.get("name"),
                        "position": p.get("position"),
                        "substitute": p.get("substitute"),
                        "shirt": p.get("shirtNumber"),
                        "rating_avg": p.get("avgRating"),
                    })
                missing = []
                for m in block.get("missingPlayers", []) or []:
                    missing.append({
                        "id": (m.get("player") or {}).get("id"),
                        "name": (m.get("player") or {}).get("name"),
                        "position": (m.get("player") or {}).get("position"),
                        "reason": m.get("reason") or m.get("type"),
                        "until": m.get("expectedEndDate"),
                    })
                out[side] = {
                    "confirmed": bool(block.get("confirmed")),
                    "formation": block.get("formation"),
                    "players": players,
                    "missing": missing,
                }
            return out

        return self._ttl_cached(f"pxi-{event_id}", ttl, _fetch)

    def statistics(self, event_id):
        data = self.http.get(f"event/{event_id}/statistics")
        if not data:
            return None
        stats = {"home": {}, "away": {}}
        for block in data.get("statistics", []):
            for group in block.get("groups", []):
                for item in group.get("statisticsItems", []):
                    name = item.get("name")
                    if not name:
                        continue
                    key = name.lower().replace(" ", "_").replace("%", "pct")
                    stats["home"][key] = item.get("home")
                    stats["away"][key] = item.get("away")
        return stats

    def incidents(self, event_id):
        data = self.http.get(f"event/{event_id}/incidents")
        if not data:
            return []
        out = []
        for i in data.get("incidents", []):
            ict = i.get("incidentType")
            icc = i.get("incidentClass")
            player = i.get("player") or i.get("playerNow") or {}
            team = i.get("team") or i.get("teamNow") or {}
            minute = i.get("minute") or i.get("time") or i.get("Period") or 0
            if minute is None:
                minute = 0
            out.append({
                "type": ict, "class": icc, "minute": minute,
                "player": player.get("name"), "team_id": team.get("id"),
                "team": team.get("name"), "is_home": i.get("isHome"),
            })
        return out

    def team_events(self, team_id, max_events=40):
        import time as _t
        now = _t.time()
        cached = getattr(self, "_team_events_cache", {})
        hit = cached.get(team_id)
        if hit and now - hit[0] < 1800:
            return hit[1]
        seen_ids = set()
        out = []
        for page in range(3):  # ~90 eventi (~2+ stagioni)
            data = self.http.get(f"team/{team_id}/events/last/{page}")
            if not data:
                break
            events = data.get("events", [])
            if not events:
                break
            new_found = False
            for e in events:
                tournament = (e.get("tournament") or {})
                ut = tournament.get("uniqueTournament") or {}
                if ut.get("id") != config.TOURNAMENT_ID:
                    continue
                if e.get("id") in seen_ids:
                    continue
                seen_ids.add(e.get("id"))
                new_found = True
                status = e.get("status") or {}
                ht = e.get("homeTeam") or {}
                at = e.get("awayTeam") or {}
                out.append({
                    "id": e.get("id"),
                    "home": ht.get("name"), "away": at.get("name"),
                    "home_id": ht.get("id"), "away_id": at.get("id"),
                    "finished": status.get("type") == "finished",
                    "start_ts": e.get("startTimestamp"),
                    "season_id": (e.get("season") or {}).get("id"),
                    "home_score": (e.get("homeScore") or {}).get("current"),
                    "away_score": (e.get("awayScore") or {}).get("current"),
                })
            if len(out) >= max_events or not new_found:
                break
        out.sort(key=lambda x: x["start_ts"] or 0, reverse=True)
        result = out[:max_events]
        cached[team_id] = (now, result)
        self._team_events_cache = cached
        return result

    def referee_events(self, ref_id):
        """Ultimi eventi arbitrari dal profilo arbitro (per media stagionale)."""
        data = self.http.get(f"referee/{ref_id}/events/last/0")
        if not data:
            return []
        out = []
        for e in data.get("events", []):
            tournament = (e.get("tournament") or {})
            ut = tournament.get("uniqueTournament") or {}
            if ut.get("id") != config.TOURNAMENT_ID:
                continue
            status = e.get("status") or {}
            if status.get("type") != "finished":
                continue
            out.append(e.get("id"))
        return out

    def team_injuries(self, team_id):
        data = self.http.get(f"team/{team_id}/injury")
        if not data:
            return []
        out = []
        for i in data.get("injuries", []):
            player = i.get("player") or {}
            desc = i.get("description") or {}
            out.append({
                "player": player.get("name"),
                "reason": desc.get("name") or i.get("status") or "infortunato",
            })
        return out

    # ------------------------------------------------------------- quote 1X2
    def event_odds(self, event_id):
        out = []
        seen = set()
        for market_id in _MARKET_IDS:
            data = self.http.get(f"event/{event_id}/odds/{market_id}/all")
            if not data:
                continue
            for m in data.get("markets", []):
                name = m.get("marketName")
                if not name or name in seen:
                    continue
                picks = []
                for c in m.get("choices", []):
                    dec = _frac2dec(c.get("fractionalValue")) or _frac2dec(c.get("initialFractionalValue"))
                    if dec:
                        picks.append((c.get("name"), dec))
                if picks:
                    seen.add(name)
                    out.append((name, picks))
        return out

    def odds_to_picks(self, event_id, source="sofascore"):
        picks = []
        for market, entries in self.event_odds(event_id):
            for pick, dec in entries:
                picks.append(OddsPick(source=source, market=market, pick=pick, odds=dec))
        return picks

    # ------------------------------------------------------------- aggregazioni
    def build_fixture(self, row, season_id):
        """Costruisce un oggetto Fixture arricchito (dettaglio, quote)."""
        event_id, home, away, h_id, a_id, ts, rnd = row
        detail = self.event_detail(event_id)
        fixture = Fixture(
            id=event_id, home=detail.get("home", home),
            away=detail.get("away", away), home_id=h_id, away_id=a_id,
            start_ts=ts, round=rnd or detail.get("round"),
            venue=detail.get("venue", ""), status=detail.get("status", ""),
            referee=detail.get("referee", {}),
        )
        fixture.odds = self.odds_to_picks(event_id)
        return fixture

    def collect_past_matches(self, season_id, max_matches=120):
        """Partite terminate della stagione corrente (per arbitri/media)."""
        out = []
        seen = set()
        for page in range(4):
            data = self.http.get(f"unique-tournament/23/season/{season_id}/events/last/{page}")
            if not data:
                break
            events = data.get("events", [])
            if not events:
                break
            new = False
            for e in events:
                status = (e.get("status") or {}).get("type")
                if status != "finished":
                    continue
                eid = e.get("id")
                if eid not in seen:
                    seen.add(eid)
                    out.append(eid)
                    new = True
            if not new:
                break
        return out[:max_matches]

    def season_results(self, season_id, max_rounds=99):
        """Risultati finiti della stagione per giornata (cache di giornata).

        Un'unica richiesta (events/last/0) restituisce tutte le partite giocate
        finora; le raggruppa per giornata con punteggio e data."""
        data = self.http.get(
            f"unique-tournament/23/season/{season_id}/events/last/0")
        if not data:
            return []
        by_round = {}
        for e in data.get("events", []):
            if (e.get("status") or {}).get("type") != "finished":
                continue
            ht = e.get("homeTeam") or {}
            at = e.get("awayTeam") or {}
            hs = (e.get("homeScore") or {}).get("current")
            as_ = (e.get("awayScore") or {}).get("current")
            rnd = (e.get("roundInfo") or {}).get("round")
            if rnd is None or hs is None or as_ is None:
                continue
            by_round.setdefault(rnd, []).append({
                "id": e.get("id"),
                "home": ht.get("name"), "away": at.get("name"),
                "home_id": ht.get("id"), "away_id": at.get("id"),
                "score": f"{hs}-{as_}",
                "hs": hs, "as": as_,
                "start_ts": e.get("startTimestamp") or 0,
            })
        rounds = [{"round": r, "matches": rounds}
                  for r, rounds in sorted(by_round.items())[-max_rounds:]]
        return rounds

    def live_events(self):
        """Partite live (tutte le competizioni, 1 richiesta) filtrate su
        Serie A. Ritorna lista di dict minimi per il monitor live."""
        data = self.http.get("sport/football/events/live")
        if not data:
            return []
        import time
        now = time.time()
        out = []
        for e in data.get("events", []):
            tournament = (e.get("tournament") or {})
            ut = tournament.get("uniqueTournament") or {}
            if ut.get("id") != config.TOURNAMENT_ID:
                continue
            st = e.get("status") or {}
            period = st.get("description") or st.get("type") or ""
            tm = e.get("time") or {}
            minute = None
            start = tm.get("currentPeriodStartTimestamp")
            if start and "half" in str(period).lower():
                elapsed = int(max(0, now - start) // 60)
                if "2nd" in period:
                    elapsed += (tm.get("initial") or 0) // 60
                minute = elapsed
            ht = e.get("homeTeam") or {}
            at = e.get("awayTeam") or {}
            hs = (e.get("homeScore") or {}).get("current")
            as_ = (e.get("awayScore") or {}).get("current")
            out.append({
                "id": e.get("id"),
                "home": ht.get("name"), "away": at.get("name"),
                "home_id": ht.get("id"), "away_id": at.get("id"),
                "hs": hs, "as": as_,
                "status": st.get("type"),
                "period": period,
                "minute": minute,
            })
        return out

    def stats_for_events(self, event_ids, workers=5):
        """Statistiche LED per lista di id partita (in parallelo, in cache)."""
        results = {}

        def fetch(eid):
            return eid, self._cached(f"stats-{eid}", lambda: self.statistics(eid))

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for eid, stats in pool.map(fetch, event_ids):
                if stats:
                    results[eid] = stats
        return results

    def incidents_for_events(self, event_ids, workers=5):
        results = {}

        def fetch(eid):
            return eid, self._cached(f"inc-{eid}", lambda: self.incidents(eid))

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for eid, incidents in pool.map(fetch, event_ids):
                results[eid] = incidents
        return results