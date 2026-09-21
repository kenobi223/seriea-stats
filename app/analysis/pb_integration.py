"""Integrazione penaltyblog nel nostro sistema predittivo.

Feature principali usate:
1. Pi Ratings — rating avanzato per forza squadre (attacco/difesa)
2. Implied Probabilities — rimuove overround dai coefficienti bookmaker
3. Dixon-Coles Bayesiano — versione avanzata del nostro predictor

Fonte: https://github.com/martineastwood/penaltyblog (MIT License)
"""
import logging

log = logging.getLogger("penaltyblog_integration")

try:
    from penaltyblog.ratings import PiRating
    from penaltyblog.implied import shin, power, odds_to_probs
    from penaltyblog.models import DixonColesModel
    HAS_PB = True
except ImportError:
    HAS_PB = False
    log.warning("penaltyblog non installato")


def calculate_pi_ratings(matches_df, k=25, home_advantage=50):
    """Calcola Pi Ratings per tutte le squadre.

    Args:
        matches_df: DataFrame con HomeTeam, AwayTeam, FTHG, FTAG, FTR
        k: velocita aggiornamento (default 25)
        home_advantage: bonus casa (default 50)

    Returns:
        dict con ratings per squadra: {team: {"attack": float, "defense": float}}
    """
    if not HAS_PB:
        return None
    try:
        pr = PiRating(k=k, home_advantage=home_advantage)
        for _, row in matches_df.iterrows():
            pr.update(
                row["HomeTeam"], row["AwayTeam"],
                row["FTHG"], row["FTAG"]
            )
        ratings = {}
        for team in pr.teams:
            ratings[team] = {
                "attack": round(pr.get_rating(team, "attack"), 2),
                "defense": round(pr.get_rating(team, "defense"), 2),
            }
        return ratings
    except Exception as e:
        log.warning("Pi Ratings errore: %s", e)
        return None


def implied_probabilities(odds_list, method="shin"):
    """Calcola probabilita implicite rimuovendo overround bookmaker.

    Args:
        odds_list: lista di (home_odds, draw_odds, away_odds)
        method: "shin", "power", o "basic"

    Returns:
        lista di {"home": float, "draw": float, "away": float}
    """
    if not HAS_PB:
        return None
    try:
        results = []
        for h, d, a in odds_list:
            if method == "shin":
                probs = shin([h, d, a])
            elif method == "power":
                probs = power([h, d, a])
            else:
                probs = odds_to_probs([h, d, a])
            results.append({
                "home": round(float(probs[0]), 4),
                "draw": round(float(probs[1]), 4),
                "away": round(float(probs[2]), 4),
            })
        return results
    except Exception as e:
        log.warning("Implied probabilities errore: %s", e)
        return None


def dixon_coles_predict(home_team, away_team, matches_df, gamma=None):
    """Predice usando Dixon-Coles Bayesiano.

    Args:
        home_team: nome squadra casa
        away_team: nome squadra ospite
        matches_df: DataFrame con HomeTeam, AwayTeam, FTHG, FTAG
        gamma: parametro di correlazione (None = auto)

    Returns:
        dict con {"home": float, "draw": float, "away": float}
    """
    if not HAS_PB:
        return None
    try:
        model = DixonColesModel()
        model.fit(matches_df)
        pred = model.predict(home_team, away_team)
        return {
            "home": round(float(pred["home"]), 4),
            "draw": round(float(pred["draw"]), 4),
            "away": round(float(pred["away"]), 4),
        }
    except Exception as e:
        log.warning("Dixon-Coles errore: %s", e)
        return None
