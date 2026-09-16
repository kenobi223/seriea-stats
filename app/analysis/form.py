"""Forma squadre: ultimi N risultati, stagione corrente, casa/trasferta."""
import logging

import config

log = logging.getLogger("form")

RESULT_CHARS = {"H": "V", "D": "N", "A": "P"}


def _outcome(event, team_id):
    if event["home_score"] is None:
        return None
    if event["home_id"] == team_id:
        gf, ga = event["home_score"], event["away_score"]
    else:
        gf, ga = event["away_score"], event["home_score"]
    if gf > ga:
        return "H"
    if gf == ga:
        return "D"
    return "A"


def build_team_form(client, team_id, name, season_id, n=config.LAST_RESULTS_N):
    events = client.team_events(team_id, max_events=40)
    finished = [e for e in events if e.get("finished")]
    current = [e for e in finished if e.get("season_id") == season_id]
    current = sorted(current, key=lambda e: e["start_ts"] or 0, reverse=True)

    last = sorted(finished, key=lambda e: e["start_ts"] or 0, reverse=True)[:n]
    last = list(reversed(last))  # dal più vecchio al più recente

    result_entries = []
    for e in last:
        res = _outcome(e, team_id)
        result_entries.append({
            "opponent": e["away"] if e["home_id"] == team_id else e["home"],
            "home": e["home_id"] == team_id,
            "score": f"{e['home_score']}-{e['away_score']}",
            "result": res,
            "week": None,
        })

    home_results = [e for e in finished if e["home_id"] == team_id][:10]
    away_results = [e for e in finished if e["away_id"] == team_id][:10]

    season_record = None
    if current:
        w = sum(1 for e in current if _outcome(e, team_id) == "H")
        d = sum(1 for e in current if _outcome(e, team_id) == "D")
        l = sum(1 for e in current if _outcome(e, team_id) == "A")
        gf = sum((e["home_score"] if e["home_id"] == team_id else e["away_score"]) or 0 for e in current)
        ga = sum((e["away_score"] if e["away_id"] == team_id else e["home_score"]) or 0 for e in current)
        season_record = {"giocate": len(current), "v": w, "n": d, "p": l, "gf": gf, "ga": ga}

    return {
        "team_id": team_id, "name": name,
        "last_results": result_entries,
        "current_season": season_record,
        "home_results": [_result_summary(e, team_id) for e in home_results],
        "away_results": [_result_summary(e, team_id) for e in away_results],
        "form_chars": "".join(
            RESULT_CHARS.get(_outcome(e, team_id), "?") for e in
            sorted(finished, key=lambda e: e["start_ts"] or 0, reverse=True)[: config.FORM_WINDOW]),
    }


def _result_summary(e, team_id):
    res = _outcome(e, team_id)
    return {
        "opponent": e["away"] if e["home_id"] == team_id else e["home"],
        "home": e["home_id"] == team_id,
        "score": f"{e['home_score']}-{e['away_score']}",
        "result": res,
    }


def h2h_between(client, team_a, team_b, k=6):
    """Confronto testa a testa: intersezione ultime partite delle due squadre."""
    a = {e["id"]: e for e in client.team_events(team_a, max_events=40)}
    b = {e["id"]: e for e in client.team_events(team_b, max_events=40)}
    common = sorted((a[eid] for eid in set(a) & set(b) if a[eid].get("finished")),
                    key=lambda e: e["start_ts"] or 0, reverse=True)
    out = []
    for e in common[:k]:
        if e["home_score"] is None:
            continue
        out.append({
            "home": e["home"], "away": e["away"],
            "score": f"{e['home_score']}-{e['away_score']}",
            "winner": "H" if e["home_score"] > e["away_score"] else (
                "A" if e["away_score"] > e["home_score"] else "D"),
        })
    return out