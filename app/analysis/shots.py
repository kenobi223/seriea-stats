"""Tiri in porta dei giocatori per ogni partita — motore "threat".

Le quote dei mercati giocatore non sono esposte gratis da Sofascore, quindi
ricostruiamo statisticamente la minaccia offensiva di ogni titolare:

  * media SOT a gara dagli ultimi match in stagione (finestra player)
  * fair odds onesti per Over 0.5 / Over 1.5 tiri in porta, dalla
    distribuzione empirica dei SOT del giocatore
  * threat score (1-10): media pesata per quanto l'avversario produce tiri
    in porta rispetto alla media della lega
  * confidenza in base a partite giocate e minuti
  * trend delle ultime gare (↑/→/↓)

Dati a partita: `shots_on_target = totalShots - shotOffTarget`.
"""
import logging

import config

log = logging.getLogger("shots")

PLAYER_WINDOW = 3          # ultime N partite per la media
MAX_PLAYERS = 5            # massimo tiratori mostrati per squadra
POSITIONS = {"A", "M", "F"}  # attaccanti e centrocampisti
_PRIOR = 0.5               # smoothing bayesiano per le probabilità


def _cached_lineup(client, event_id):
    return client._cached(f"lu-{event_id}",
                          lambda: client.lineups(event_id))


def _fair_odds(sots):
    """Quote fair Over 0.5 / Over 1.5 tiri in porta dalla distribuzione."""
    n = len(sots)
    if n < 1:
        return None, None
    k1 = sum(1 for v in sots if v >= 1)
    k2 = sum(1 for v in sots if v >= 2)
    p1 = (k1 + _PRIOR) / (n + 1)
    p2 = (k2 + _PRIOR) / (n + 1)
    o1 = 1 / p1 if p1 > 0 else None
    o2 = 1 / p2 if p2 > 0 else None
    return o1, o2


def _trend(sots):
    if len(sots) < 3:
        return None
    recent = sum(sots[:2])
    earlier = sots[2:]
    prev_avg = sum(earlier) / len(earlier)
    recent_avg = recent / 2
    if recent_avg > prev_avg + 0.25:
        return "up"
    if recent_avg < prev_avg - 0.25:
        return "down"
    return "flat"


def _confidence(played, minutes):
    if played >= 3 and minutes >= played * 45:
        return "high"
    if played >= 2:
        return "medium"
    return "low"


def _team_pstats(client, team_id, season_id):
    """Statistiche per giocatore dagli ultimi PLAYER_WINDOW match finiti."""
    events = client.team_events(team_id, max_events=40)
    finished = sorted(
        [e for e in events if e.get("finished")
         and e.get("season_id") == season_id],
        key=lambda e: e.get("start_ts") or 0, reverse=True)[:PLAYER_WINDOW]
    agg = {}
    for e in finished:
        lu = _cached_lineup(client, e["id"])
        if not lu:
            continue
        players = (lu.get("home") or {}).get("players", []) if \
            e["home_id"] == team_id else (lu.get("away") or {}).get("players", [])
        for p in players:
            pid, sot = p.get("id"), p.get("shots_on_target")
            if pid is None or sot is None:
                continue
            rec = agg.setdefault(pid, {
                "id": pid, "name": p.get("name", ""),
                "pos": p.get("position", ""),
                "sots": [], "minutes": 0, "played": 0,
            })
            rec["sots"].append(sot)
            rec["minutes"] += p.get("minutes") or 0
            rec["played"] += 1
    out = []
    for rec in agg.values():
        if not rec["played"]:
            continue
        o1, o2 = _fair_odds(rec["sots"])
        out.append({
            "id": rec["id"], "name": rec["name"], "pos": rec["pos"],
            "avg": round(sum(rec["sots"]) / rec["played"], 2),
            "played": rec["played"],
            "minutes": rec["minutes"],
            "conf": _confidence(rec["played"], rec["minutes"]),
            "trend": _trend(rec["sots"]),
            "fair_o05": None if o1 is None else round(o1, 2),
            "fair_o15": None if o2 is None else round(o2, 2),
            "last": rec["sots"][:PLAYER_WINDOW],
        })
    out.sort(key=lambda r: r["avg"], reverse=True)
    return out


def _side_players(fx, tid, cache):
    src = (fx.probable_xi or {}).get("home") if fx.home_id == tid \
        else (fx.probable_xi or {}).get("away")
    if not src:
        src = (fx.lineups or {}).get("home") if fx.home_id == tid \
            else (fx.lineups or {}).get("away")
    if not src:
        return []
    starters = [p for p in src.get("players", []) or []
                if not p.get("substitute")]
    if not starters:
        return []
    ids = {p.get("id") for p in starters}
    roster = cache.get(tid) or []
    relevant = [r for r in roster if r["id"] in ids
                and r["pos"] in POSITIONS]
    relevant.sort(key=lambda r: r["avg"], reverse=True)
    return relevant[:MAX_PLAYERS]


def _apply_threat(fx, team_sot, league_sot):
    """Riempe threat/expected per ogni lato con il fattore avversario."""
    opp_ids = {"home": fx.away_id, "away": fx.home_id}
    for side, rows in fx.player_shots.items():
        opp = opp_ids[side]
        opp_sot = (team_sot or {}).get(opp)
        factor = 1.0
        if opp_sot and league_sot:
            factor = opp_sot / league_sot
        for r in rows:
            expected = round(r["avg"] * factor, 2)
            r["expected"] = expected
            r["threat"] = min(10, max(1, round(expected * 2.5)))
            r["factor"] = round(factor, 2)


def compute_for_fixtures(client, fixtures, season_id, team_sot=None,
                         league_sot=None):
    """Calcola fx.player_shots = {"home": [...], "away": [...]}."""
    cache = {}
    for fx in fixtures:
        fx.player_shots = {"home": [], "away": []}
        for side, tid in (("home", fx.home_id), ("away", fx.away_id)):
            if not tid:
                continue
            if tid not in cache:
                try:
                    cache[tid] = _team_pstats(client, tid, season_id)
                except Exception as e:
                    log.debug("pstats squadra %s: %s", tid, e)
                    cache[tid] = []
            fx.player_shots[side] = _side_players(fx, tid, cache)
        _apply_threat(fx, team_sot, league_sot)
    return fx.player_shots