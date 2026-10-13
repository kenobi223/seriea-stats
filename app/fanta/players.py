"""DB giocatori Serie A (Sofascore): indici, ricerca, statistiche cached.

L'indice giocatori viene costruito dalla rosa di ogni squadra (standings →
team_players) e cachato in kv `fanta_index.json` (TTL 12h). Le statistiche
singole (voto recente, gol, minuti) sono cachate in `fanta_stats.json`
con TTL 24h per non martellare Sofascore.
"""
import logging
import threading
import time

import config
from app.core import kv

log = logging.getLogger("fanta.players")

_CLIENT = None
_client_lock = threading.Lock()
_SEASON_ID = None
_season_lock = threading.Lock()

INDEX_KEY = "fanta_index.json"
STATS_KEY = "fanta_stats.json"
INDEX_TTL = 12 * 3600
STATS_TTL = 24 * 3600
MAX_STATS_CACHE = 800

POS_MAP = {
    "Goalkeeper": "P", "Defender": "D", "Midfielder": "C", "Attacker": "A",
    "G": "P", "D": "D", "M": "C", "F": "A", "P": "P", "C": "C", "A": "A",
}


def _client():
    global _CLIENT
    with _client_lock:
        if _CLIENT is None:
            from app.sources.sofascore import SofascoreClient
            _CLIENT = SofascoreClient()
        return _CLIENT


def _season_id():
    global _SEASON_ID
    with _season_lock:
        if _SEASON_ID is None:
            s = _client().resolve_season()
            _SEASON_ID = (s or {}).get("id")
        return _SEASON_ID


def _norm_pos(position):
    return POS_MAP.get(str(position or "").strip(), "?")


def build_index(store):
    """Indice giocatori di tutte le squadre Serie A. Cached 12h (kv).
    Le squadre sono richieste in parallelo (5 worker) per stare nei tempi
    di una richiesta web anche a freddo (Sofascore via Tor)."""
    cached = kv.read_json(INDEX_KEY)
    if isinstance(cached, dict) and cached.get("players") and \
            time.time() - (cached.get("t") or 0) < INDEX_TTL:
        return cached["players"]
    teams = []
    for row in store.get("standings") or []:
        tid = row.get("team_id")
        name = row.get("name")
        if tid and name:
            teams.append((tid, name))
    if not teams:
        log.warning("fanta: nessuna squadra in standings")
        return cached.get("players") if isinstance(cached, dict) else []
    cl = _client()
    players = []
    from concurrent.futures import ThreadPoolExecutor

    def _fetch(team):
        tid, tname = team
        try:
            return tid, tname, cl.team_players(tid) or []
        except Exception as e:
            log.warning("fanta: team_players(%s) fallita: %s", tid, e)
            return tid, tname, []

    with ThreadPoolExecutor(max_workers=5) as pool:
        for tid, tname, squad in pool.map(_fetch, teams):
            for p in squad:
                if not p.get("id"):
                    continue
                players.append({
                    "id": p["id"],
                    "name": p.get("name") or "?",
                    "role": _norm_pos(p.get("position")),
                    "team": tname,
                    "team_id": tid,
                })
    if players:
        kv.write_json(INDEX_KEY, {"t": int(time.time()), "players": players})
        log.info("fanta: indice costruito (%d giocatori, %d squadre)",
                 len(players), len(teams))
    return players


def search(store, query, limit=15):
    """Ricerca fuzzy-leggera per nome (o squadra). Punteggio: prefisso >
    sottostringa > tutti i token presenti."""
    q = str(query or "").strip().lower()
    if not q:
        return []
    players = build_index(store)
    tokens = [t for t in q.split() if t]
    scored = []
    for p in players:
        name = (p.get("name") or "").lower()
        team = (p.get("team") or "").lower()
        score = 0
        if name.startswith(q) or team.startswith(q):
            score = 3
        elif q in name or q in team:
            score = 2
        elif tokens and all(t in name for t in tokens):
            score = 1
        if score:
            scored.append((score, len(name), p))
    scored.sort(key=lambda x: (-x[0], x[1], x[2].get("name") or ""))
    return [p for _, _, p in scored[:limit]]


def _load_stats_blob():
    blob = kv.read_json(STATS_KEY)
    return blob if isinstance(blob, dict) else {}


def _prune(blob):
    now = time.time()
    items = [(k, v) for k, v in blob.items()
             if isinstance(v, dict) and now - (v.get("t") or 0) < STATS_TTL]
    items.sort(key=lambda kv_: -(kv_[1].get("t") or 0))
    return {k: v for k, v in items[:MAX_STATS_CACHE]}


def player_stats(pid):
    """Statistiche fanta di un giocatore: voto recente, gol, minuti, infortunio."""
    blob = _load_stats_blob()
    hit = blob.get(str(pid))
    if hit and time.time() - (hit.get("t") or 0) < STATS_TTL:
        return hit.get("data")
    cl = _client()
    data = {"id": pid}
    try:
        detail = cl.player_detail(pid) or {}
        data["name"] = detail.get("name")
        data["team"] = detail.get("team")
        data["position"] = _norm_pos(detail.get("position"))
    except Exception as e:
        log.debug("fanta: player_detail(%s): %s", pid, e)
    try:
        ratings = cl.player_last_ratings(pid) or []
        vals = [r["rating"] for r in ratings[:8] if r.get("rating")]
        data["ratings"] = vals
        data["avg_rating"] = round(sum(vals) / len(vals), 2) if vals else None
        if len(vals) >= 4:
            recent = sum(vals[:3]) / 3
            older = sum(vals[3:]) / len(vals[3:])
            data["trend"] = "up" if recent > older + 0.15 else \
                "down" if recent < older - 0.15 else "flat"
        else:
            data["trend"] = None
    except Exception as e:
        log.debug("fanta: player_last_ratings(%s): %s", pid, e)
        data["ratings"] = []
    try:
        sid = _season_id()
        if sid:
            st = cl.player_season_stats(pid, sid) or {}
            data.update({k: st.get(k) for k in
                         ("appearances", "minutes", "goals", "assists",
                          "total_shots", "rating")})
    except Exception as e:
        log.debug("fanta: player_season_stats(%s): %s", pid, e)
    blob[str(pid)] = {"t": int(time.time()), "data": data}
    kv.write_json(STATS_KEY, _prune(blob))
    return data
