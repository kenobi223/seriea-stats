"""Test minimo per la conversione quote americane -> decimali (ESPN).

Campiona la struttura reale DraftKings vista su scoreboard:

    "moneyline": {
      "home": {"close": {"odds": "-475"}},
      "draw": {"close": {"odds": "+475"}},
      "away": {"close": {"odds": "+800"}}
    }
"""
from app.sources.espn import EspnClient, _american_to_decimal


def _picks(comp):
    c = EspnClient()
    c._events_by_id = {comp["id"]: comp}
    return c.odds_to_picks(comp["id"])


if __name__ == "__main__":
    # 1) conversioni note
    assert _american_to_decimal("-475") == 1.211
    assert _american_to_decimal("+800") == 9.0
    assert _american_to_decimal("+470") == 5.7
    assert _american_to_decimal("-110") == 1.909

    # 2) parsing moneyline DraftKings -> 1 = 1.211, X = 5.7, 2 = 9.0
    comp = {"id": "999", "competitors": [{}, {}], "odds": [{"moneyline": {
        "home": {"close": {"odds": "-475"}},
        "draw": {"close": {"odds": "+470"}},
        "away": {"close": {"odds": "+800"}},
    }}]}
    picks = _picks(comp)
    by_pick = {p.pick: p.odds for p in picks}
    assert by_pick == {"1": 1.211, "X": 5.7, "2": 9.0}, by_pick
    assert all(p.market == "Full time" and p.source == "espn" for p in picks)

    # 3) senza quote -> lista vuota (fallback silenzioso)
    assert _picks({"id": "8", "competitors": [{}, {}]}) == []

    print("ok:", by_pick)