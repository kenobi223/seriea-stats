"""Gol attesi (xG) per squadra: media xG fatti/subiti in stagione.

Sofascore espone ``expected_goals`` (e ``expected_goals_on_target``, quasi
sempre presente) nelle statistiche di partita: dati che sono GIÀ nella cache
locale (file ``data/cache/stats-<id>.json``) dopo qualsiasi ciclo, quindi
questa feature costa ~zero richieste di rete e va solo a leggere la cache.

Il modulo produce, per ogni squadra, le medie a gara di:

  * ``xg_for``  — xG prodotti (dai tiri della squadra);
  * ``xg_ag``   — xG concessi (dai tiri dell'avversario);

usate dal predictor per affinare le valutazioni attacco/difesa del motore
Poisson (che altrimenti si baserebbero solo sui gol reali, rumorosi con pochi
campioni). Se lo xG per-matematch manca per qualche partita, queste partite
vengono scartate e la media è calcolata sulle restanti.
"""
import logging

import config

log = logging.getLogger("xg")


def _num(item):
    try:
        return float(item)
    except (TypeError, ValueError):
        return None


def team_xg_table(client, team_id, season_id, window=None):
    """Media xG fatti/subiti a gara per una squadra in stagione.

    ``window`` (opzionale) limita la finestra alle ultime N partite finite;
    di default usa tutta la stagione disponibile.
    """
    try:
        events = client.team_events(team_id, max_events=40)
    except Exception as e:
        log.debug("xg squadra %s: eventi non disponibili: %s", team_id, e)
        return None
    finished = [e for e in events if e.get("finished")
                and e.get("season_id") == season_id]
    finished.sort(key=lambda e: e.get("start_ts") or 0, reverse=True)
    if window:
        finished = finished[:window]
    if not finished:
        return None

    xg_for, xg_ag = [], []
    for e in finished:
        try:
            stats = client._cached(f"stats-{e['id']}",
                                   lambda: client.statistics(e["id"]))
        except Exception as ex:
            log.debug("xg squadra %s: stats %s non disponibili: %s",
                      team_id, e.get("id"), ex)
            continue
        if not stats:
            continue
        hx = _num((stats.get("home") or {}).get("expected_goals"))
        ax = _num((stats.get("away") or {}).get("expected_goals"))
        if hx is None or ax is None:
            continue
        if e.get("home_id") == team_id:
            xg_for.append(hx)
            xg_ag.append(ax)
        elif e.get("away_id") == team_id:
            xg_for.append(ax)
            xg_ag.append(hx)
    if not xg_for or not xg_ag:
        return None
    return {
        "team_id": team_id,
        "played": len(xg_for),
        "xg_for": sum(xg_for) / len(xg_for),
        "xg_ag": sum(xg_ag) / len(xg_ag),
        "last": [round(f, 2) for f in xg_for[:3]],
    }


def compute_all(client, team_ids, season_id, window=None):
    """Calcola la mappa {team_id: table} per tutte le squadre richieste."""
    out = {}
    for tid in team_ids:
        if not tid:
            continue
        try:
            tab = team_xg_table(client, tid, season_id, window=window)
        except Exception as e:
            log.debug("xg squadra %s: %s", tid, e)
            tab = None
        if tab:
            out[tid] = tab
    return out


def league_xg(team_xg):
    """Medie di campionato di xG (per scalare i numeri a media gol)."""
    if not team_xg:
        return None
    g = [t["xg_for"] for t in team_xg.values()]
    d = [t["xg_ag"] for t in team_xg.values()]
    if not g or not d:
        return None
    return {"scored": sum(g) / len(g), "conceded": sum(d) / len(d)}