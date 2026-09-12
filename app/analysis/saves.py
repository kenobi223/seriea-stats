"""Parate dei portieri per ogni partita — motore "keeps".

Il mercato "parate del portiere" (es. over 2.5 / 3.5 parate) non è esposto
liberamente, quindi ricostruiamo la stima:

  * media parate a gara della squadra dagli ultimi match finiti in stagione
    (fonte: statistics endpoint di Sofascore, `goalkeeper_saves`/`total_saves`,
    già in cache -> praticamente gratuito dopo il primo calcolo);
  * il fattore chiave è quanti tiri in porta la squadra AVVERSARIA produce
    (più SOT concede, più parate servono): aggiustiamo la media col rapporto
    tra SOT avversario e media di campionato, come per il threat dei tiri;
  * fair odds onesti per Over 2.5 parate dalla distribuzione empirica;
  * nome del portiere titolare probabile quando disponibile (XI probabile);
  * confidenza in base alle partite di campione.

Dati a partita: una per squadra (il portiere che gioca quasi sempre).
"""
import logging

import config

log = logging.getLogger("saves")

GK_POS = "G"          # posizione portiere nei fixture Sofascore
_PRIOR = 1.0          # smoothing bayesiano per la probabilità dell'over


def _team_saves_table(client, team_id, season_id):
    """Media parate a gara + SOT subiti dagli ultimi SAVES_WINDOW match."""
    events = client.team_events(team_id, max_events=40)
    finished = sorted(
        [e for e in events if e.get("finished")
         and e.get("season_id") == season_id],
        key=lambda e: e.get("start_ts") or 0, reverse=True)[:config.SAVES_WINDOW]
    saves = []
    opp_sot = []
    for e in finished:
        stats = client._cached(f"stats-{e['id']}",
                               lambda: client.statistics(e["id"]))
        if not stats:
            continue
        side = "home" if e["home_id"] == team_id else "away"
        block = stats.get(side) or {}
        sv = block.get("goalkeeper_saves")
        if sv is None:
            sv = block.get("total_saves")
        if sv is None:
            continue
        try:
            saves.append(int(sv))
        except (TypeError, ValueError):
            continue
        opp_side = "away" if side == "home" else "home"
        sot = (stats.get(opp_side) or {}).get("shots_on_target")
        if isinstance(sot, (int, float)):
            opp_sot.append(float(sot))
    if not saves:
        return None
    return {
        "avg": round(sum(saves) / len(saves), 2),
        "played": len(saves),
        "saves": saves,
        "opp_sot": round(sum(opp_sot) / len(opp_sot), 2) if opp_sot else None,
        "n_sot": len(opp_sot),
    }


def _gk_name(fx, side, tid):
    """Nome del portiere titolare probabile (se indicato dal XI)."""
    src = (fx.probable_xi or {}).get("home") if side == "home" \
        else (fx.probable_xi or {}).get("away")
    if not src:
        src = (fx.lineups or {}).get("home") if side == "home" \
            else (fx.lineups or {}).get("away")
    if not src:
        return None
    for p in src.get("players", []) or []:
        if p.get("substitute"):
            continue
        if (p.get("position") or "").upper() == GK_POS:
            return p.get("name")
    return None


def _over_prob(saves, threshold):
    """Probabilità di superare `threshold` parate dalla distribuzione."""
    n = len(saves)
    if n < 1:
        return None, None
    k = sum(1 for v in saves if v >= threshold)
    # Bayes + dinamica: tira leggermente la probabilità verso la media lega
    p = (k + _PRIOR * (config.SAVES_LEAGUE_FLOOR / threshold)) / (n + _PRIOR)
    return min(0.97, p), round(1 / p, 2) if p > 0 else None


def compute_for_fixtures(client, fixtures, season_id, team_saves=None,
                         league_saves=None, league_sot=None):
    """Calcola fx.keeper_saves = {"home": {...}, "away": {...}}."""
    cache = team_saves or {}
    league_saves = league_saves or config.SAVES_LEAGUE_FLOOR
    for fx in fixtures:
        fx.keeper_saves = {"home": None, "away": None}
        for side, tid in (("home", fx.home_id), ("away", fx.away_id)):
            if not tid:
                continue
            if tid not in cache:
                try:
                    cache[tid] = _team_saves_table(client, tid, season_id)
                except Exception as e:
                    log.debug("saves squadra %s: %s", tid, e)
                    cache[tid] = None
            tab = cache[tid]
            if not tab:
                continue
            opp_tid = fx.away_id if side == "home" else fx.home_id
            opp_tab = (league_sot if league_sot else None)
            opp_sot = None
            if league_sot and (cache.get(opp_tid) or {}).get("opp_sot"):
                opp_sot = (cache[opp_tid] or {}).get("opp_sot")
            elif league_sot and opp_tab:
                opp_sot = league_sot
            factor = 1.0
            if opp_sot and league_sot:
                factor = opp_sot / league_sot
            expected = round(tab["avg"] * factor, 2)
            p_o25, fair_o25 = _over_prob(tab["saves"], config.SAVES_BET_THRESHOLD)
            gk = _gk_name(fx, side, tid)
            fx.keeper_saves[side] = {
                "team": fx.home if side == "home" else fx.away,
                "gk": gk,
                "avg": tab["avg"],
                "expected": expected,
                "played": tab["played"],
                "opp_sot": round(opp_sot, 2) if opp_sot else None,
                "league_f": round(league_saves, 2),
                "factor": round(factor, 2),
                "conf": _confidence(tab["played"]),
                "threshold": config.SAVES_BET_THRESHOLD,
                "over_prob": p_o25,
                "fair_over": fair_o25,
                "pick": "over 2.5 parate" if (p_o25 or 0) >= config.SAVES_BET_MIN_PROB
                else None,
                "last": tab["saves"][:config.SAVES_WINDOW],
            }
    return fx.keeper_saves


def _confidence(played):
    if played >= 3:
        return "alta"
    if played == 2:
        return "media"
    return "bassa"