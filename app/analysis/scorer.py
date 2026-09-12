"""Probabilità di segnare gol per ogni giocatore titolare.

Combina:
  * gol segnati ultime 5 partite (incidenti)
  * tiri in porta medi (shots on target)
  * minuti giocati (forma fisica)
  * media gol subiti dall'avversario (difesa avversaria)
  * fattore casa/trasferta
"""
import logging
import math

import config

log = logging.getLogger("scorer")

PLAYER_WINDOW = 5
_PRIOR_GOALS = 0.4


def _cached_lineup(client, event_id):
    return client._cached(f"lu-{event_id}",
                          lambda: client.lineups(event_id))


def _cached_incidents(client, event_id):
    return client._cached(f"inc-{event_id}",
                          lambda: client.incidents(event_id))


def _team_goals_per_match(client, team_id, season_id):
    """Media gol segnati dalla squadra nelle ultime partite della stagione."""
    events = client.team_events(team_id, max_events=40)
    finished = sorted(
        [e for e in events if e.get("finished")
         and e.get("season_id") == season_id],
        key=lambda e: e.get("start_ts") or 0, reverse=True)[:PLAYER_WINDOW]
    if not finished:
        return 1.2
    total_goals = 0
    for e in finished:
        if e["home_id"] == team_id:
            total_goals += (e.get("home_score") or 0)
        else:
            total_goals += (e.get("away_score") or 0)
    return total_goals / len(finished)


def _opponent_goals_conceded(form):
    """Media gol subiti dalla squadra avversaria (dalla forma della squadra)."""
    if not form:
        return 1.3
    last_results = form.get("last_results") or []
    if not last_results:
        return 1.3
    total_conceded = 0
    count = 0
    for r in last_results:
        try:
            score = r.get("score", "0-0")
            parts = score.split("-")
            if len(parts) == 2:
                gf = int(parts[0].strip())
                ga = int(parts[1].strip())
                if r.get("home"):
                    total_conceded += ga
                else:
                    total_conceded += gf
                count += 1
        except (ValueError, IndexError):
            pass
    return total_conceded / max(count, 1)


def _incident_for_team(inc, event, team_id):
    """L'incidente appartiene a `team_id`? team_id se presente, altrimenti is_home."""
    tid = inc.get("team_id")
    if tid is not None:
        return tid == team_id
    ih = inc.get("is_home")
    if ih is not None:
        return (event.get("home_id") == team_id) == ih
    return False


def _player_goals(client, team_id, season_id, player_name):
    """Gol segnati dal giocatore negli ultimi PLAYER_WINDOW match finiti."""
    events = client.team_events(team_id, max_events=40)
    finished = sorted(
        [e for e in events if e.get("finished")
         and e.get("season_id") == season_id],
        key=lambda e: e.get("start_ts") or 0, reverse=True)[:PLAYER_WINDOW]
    if not finished:
        return 0

    pname = (player_name or "").lower()
    total_goals = 0
    for e in finished:
        incs = _cached_incidents(client, e["id"])
        if not incs:
            continue
        for inc in incs:
            if inc.get("type") not in ("goal", "penalty"):
                continue
            if not _incident_for_team(inc, e, team_id):
                continue
            if inc.get("player") and inc["player"].lower() == pname:
                total_goals += 1
    return total_goals


def _player_stats(client, team_id, season_id, player_name):
    """Statistiche giocatore: SOT medi, minuti giocati, presenze."""
    events = client.team_events(team_id, max_events=40)
    finished = sorted(
        [e for e in events if e.get("finished")
         and e.get("season_id") == season_id],
        key=lambda e: e.get("start_ts") or 0, reverse=True)[:PLAYER_WINDOW + 2]
    total_sot = 0
    total_minutes = 0
    matches = 0
    for e in finished:
        lu = _cached_lineup(client, e["id"])
        if not lu:
            continue
        side = "home" if e["home_id"] == team_id else "away"
        players = (lu.get(side) or {}).get("players", [])
        for p in players:
            if p.get("name") and p["name"].lower() == player_name.lower():
                sot = p.get("shots_on_target")
                if sot is not None:
                    total_sot += sot
                minutes = p.get("minutes") or 0
                total_minutes += minutes
                matches += 1
                break
    avg_sot = total_sot / max(matches, 1)
    avg_minutes = total_minutes / max(matches, 1)
    return avg_sot, avg_minutes, matches


def _defense_factor(goals_conceded):
    """Fattore difesa avversaria: più gol subiti = più facile segnare."""
    if goals_conceded >= 2.0:
        return 1.35
    if goals_conceded >= 1.7:
        return 1.2
    if goals_conceded >= 1.4:
        return 1.1
    if goals_conceded >= 1.1:
        return 1.0
    if goals_conceded >= 0.8:
        return 0.9
    return 0.8


def _position_share(position):
    """Quota media di gol della squadra attribuibile alla posizione."""
    pos = (position or "").upper()
    if pos in ("F", "A", "FW", "ST", "CF"):
        return 0.38
    if pos in ("M", "MF", "CM", "AM", "LM", "RM"):
        return 0.22
    if pos in ("D", "DF", "CB", "LB", "RB"):
        return 0.06
    return 0.2


def _home_away_factor(is_home):
    """Fattore casa/trasferta."""
    return 1.08 if is_home else 0.92


def _position_factor(position):
    """Fattore posizione: attaccanti segnano più dei centrocampisti."""
    pos = (position or "").upper()
    if pos in ("F", "A", "FW", "ST", "CF"):
        return 1.25
    if pos in ("M", "MF", "CM", "AM", "LM", "RM"):
        return 0.9
    if pos in ("D", "DF", "CB", "LB", "RB"):
        return 0.5
    return 0.8


def _player_historical_rate(goals_last5, matches_played):
    """Tasso gol storico del giocatore (gol/partita), con prior minimo."""
    if matches_played <= 0:
        return None
    return goals_last5 / matches_played


def _expected_goals(team_goals_per_match, player_hist_rate, matches_played,
                    shots_avg, position, minutes_avg):
    """Gol attesi del giocatore per questa partita.

    Usa il dato storico del giocatore (gol/partita ultime 5) se disponibile,
    altrimenti la quota di gol della squadra per la sua posizione. La media
    SOT e i minuti correggono in modo lieve il tasso.
    """
    pos_share = _position_share(position)
    prior = max(team_goals_per_match * pos_share, 0.04)

    if player_hist_rate is not None and matches_played > 0:
        # blend storico vs attesa posizione con smoothing bayesiano:
        # più partite ha giocato, più conta il tasso reale del giocatore
        weight = min(_PRIOR_GOALS, 0.8 / max(matches_played, 1))
        base = player_hist_rate * (1 - weight) + prior * weight
    else:
        base = prior

    # correzioni lievi da SOT e minuti (forma fisica)
    if shots_avg is not None:
        if shots_avg >= 1.5:
            base *= 1.15
        elif shots_avg >= 1.0:
            base *= 1.07
        elif shots_avg < 0.2:
            base *= 0.85

    if minutes_avg >= 75:
        base *= 1.05
    elif minutes_avg < 40:
        base *= 0.8

    return base


def compute_scorer_probability(expected_goals, defense_f, home_f, position_f):
    """Probabilità di segnare almeno un gol (Poisson: 1 - e^-lambda).

    Il totale dei fattori è deliberatamente contenuto: la difesa avversaria,
    la posizione e il fattore casa muovono la probabilità di pochi punti
    percentuale, come accade nelle quote reali dell'Anytime Goalscorer.
    """
    raw = expected_goals * defense_f * home_f * position_f
    prob = 1 - math.exp(-raw)
    return min(max(prob, 0.02), 0.60)


def compute_for_fixtures(client, fixtures, season_id):
    """Calcola scorer_probabilities per ogni fixture.

    Ritorna dict fixture_key -> {"home": [...], "away": [...]}.
    Ogni giocatore ha: name, position, prob, goals_last5, avg_sot, threat.
    """
    results = {}
    team_cache = {}

    for fx in fixtures:
        fx.scorer_probabilities = {"home": [], "away": []}

        for side, tid, opp_form in (
            ("home", fx.home_id, fx.form_away),
            ("away", fx.away_id, fx.form_home),
        ):
            if not tid:
                continue

            name = fx.home if side == "home" else fx.away
            is_home = (side == "home")

            # team goals per match
            if tid not in team_cache:
                team_cache[tid] = _team_goals_per_match(client, tid, season_id)
            team_gpm = team_cache[tid]

            # opponent goals conceded
            opp_gpm = _opponent_goals_conceded(opp_form)

            # get probable lineup players
            pxi = (fx.probable_xi or {}).get(side) or {}
            lu_data = (fx.lineups or {}).get(side) or {}
            players = pxi.get("players") or lu_data.get("players") or []
            starters = [p for p in players if not p.get("substitute")]

            for p in starters:
                pname = p.get("name")
                if not pname:
                    continue
                pos = p.get("position", "")

                # player specific stats
                goals_last5 = _player_goals(client, tid, season_id, pname)
                avg_sot, avg_minutes, presenze = _player_stats(
                    client, tid, season_id, pname)
                matches_played = presenze

                # expected goals (gol attesi per questa partita)
                hist_rate = _player_historical_rate(goals_last5, matches_played)
                expected = _expected_goals(team_gpm, hist_rate, matches_played,
                                           avg_sot, pos, avg_minutes)

                # factors
                defense_f = _defense_factor(opp_gpm)
                pos_f = _position_factor(pos)
                home_f = _home_away_factor(is_home)

                prob = compute_scorer_probability(
                    expected, defense_f, home_f, pos_f)

                # threat score 1-10
                threat = min(10, max(1, round(prob * 15)))

                fx.scorer_probabilities[side].append({
                    "name": pname,
                    "position": pos,
                    "prob": round(prob, 4),
                    "prob_pct": round(prob * 100, 1),
                    "expected_goals": round(expected, 3),
                    "goals_last5": goals_last5,
                    "matches_last5": matches_played,
                    "avg_sot": round(avg_sot, 2),
                    "avg_minutes": round(avg_minutes, 0),
                    "threat": threat,
                    "opp_goals_conceded": round(opp_gpm, 2),
                    "factors": {
                        "defense": round(defense_f, 2),
                        "position": round(pos_f, 2),
                        "home_away": round(home_f, 2),
                    },
                })

            # sort by probability
            fx.scorer_probabilities[side].sort(
                key=lambda x: x["prob"], reverse=True)

        key = f"{fx.home}-{fx.away}"
        results[key] = fx.scorer_probabilities

    return results
