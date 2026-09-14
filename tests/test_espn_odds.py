"""Test minimo per le quote Bet365 1X2 (decimali) via core.api ESPN.

Campiona la struttura reale Bet365 vista su sports.core.api.espn.com:

    "homeTeamOdds": {"odds": {"value": 1.2}},
    "drawOdds":     {"value": 5.75},
    "awayTeamOdds": {"odds": {"value": 15.0}}
"""
from app.sources.espn import EspnClient


def _picks(comp):
    c = EspnClient()
    comp.setdefault("odds_raw", comp.pop("odds", []))
    c._events_by_id = {comp["id"]: comp}
    return c.odds_to_picks(comp["id"])


if __name__ == "__main__":
    # 1) parsing Bet365 (decimali diretti) -> 1 = 1.2, X = 5.75, 2 = 15.0
    comp = {"id": "401874933", "competitors": [{}, {}], "odds": [
        {"provider": {"name": "DraftKings"},
         "homeTeamOdds": {"current": {"moneyLine": {"decimal": 1.21}}}},
        {"provider": {"name": "Bet 365"},
         "homeTeamOdds": {"odds": {"value": 1.2}},
         "drawOdds": {"value": 5.75},
         "awayTeamOdds": {"odds": {"value": 15.0}}},
    ]}
    picks = _picks(comp)
    by_pick = {p.pick: p.odds for p in picks}
    assert by_pick == {"1": 1.2, "X": 5.75, "2": 15.0}, by_pick
    assert all(p.market == "Full time" and p.source == "espn" for p in picks)

    # 2) solo DraftKings (niente provider Bet365) -> lista vuota
    comp_dk = {"id": "8", "competitors": [{}, {}], "odds": [
        {"provider": {"name": "DraftKings"},
         "homeTeamOdds": {"current": {"moneyLine": {"decimal": 1.21}}}}]}
    assert _picks(comp_dk) == []

    # 3) senza quote -> lista vuota (fallback silenzioso)
    assert _picks({"id": "8", "competitors": [{}, {}]}) == []

    # 4) quote con una gamba mancante -> saltata
    comp_part = {"id": "9", "competitors": [{}, {}], "odds": [
        {"provider": {"name": "Bet 365"},
         "homeTeamOdds": {"odds": {"value": 2.0}},
         "drawOdds": {"value": None},
         "awayTeamOdds": {"odds": {"value": 3.5}}}]}
    assert {p.pick: p.odds for p in _picks(comp_part)} == {"1": 2.0, "2": 3.5}

    print("ok:", by_pick)