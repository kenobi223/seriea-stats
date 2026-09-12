"""Mercati condivisi del motore pronostici.

Unica fonte di verità per i mercati usati da predictor, tracker e tipster:
chiavi, label, conversione esito reale <-> pick, de-juice delle quote e
blend. Ogni modulo usa così le stesse tabelle e lo stesso metodo di rimozione
del margine del bookmaker (de-juice), sul filone dell'articolo "Beating the
bookies with their own numbers" (arXiv:1710.02824).
"""
from __future__ import annotations

# mercato -> esiti (chiavi usate nelle "probs" del predictor)
MARKETS = {
    "1x2": ("1", "x", "2"),
    "over_under": ("over_2.5", "under_2.5"),
    "btts": ("si", "no"),
}

# chiave esito -> label "pick" mostrata all'utente / usata dai best_bets
PICK_LABELS = {
    "1": "1",
    "x": "x",
    "2": "2",
    "over_2.5": "over 2.5",
    "under_2.5": "under 2.5",
    "si": "btts si",
    "no": "btts no",
}


def keys(market):
    """Le possibili chiavi di un mercato."""
    return MARKETS[market]


def label(market, key):
    """Label "pick" leggibile per una (mercato, chiave)."""
    return PICK_LABELS.get(key, key)


def pick_to_market_key(pick):
    """Converte un pick testuale (es. "over 2.5") in (mercato, chiave)."""
    p = str(pick).strip().lower()
    if p in ("1", "x", "2"):
        return "1x2", p
    if p == "over 2.5":
        return "over_under", "over_2.5"
    if p == "under 2.5":
        return "over_under", "under_2.5"
    if p == "btts si":
        return "btts", "si"
    if p == "btts no":
        return "btts", "no"
    return None


def match_outcomes(home, away):
    """Esiti reali dei mercati per un punteggio home-away finale."""
    if home > away:
        o3 = "1"
    elif home < away:
        o3 = "2"
    else:
        o3 = "x"
    totals = home + away
    return {
        "1x2": o3,
        "over_under": "over_2.5" if totals > 2.5 else "under_2.5",
        "btts": "si" if home > 0 and away > 0 else "no",
    }


def dejuice(implied):
    """Rimuove il margine del bookmaker dalle probabilità implicite.

    ``implied`` è {key: prob implicita dal 1/quota}. Restituisce probabilità
    che sommano a 1 (normalizzazione proporzionale) o None se non abbastanza
    esiti validi.
    """
    if not implied:
        return None
    filtered = {k: v for k, v in implied.items()
                if isinstance(v, (int, float)) and v > 0}
    if len(filtered) < 2:
        return None
    tot = sum(filtered.values())
    if tot <= 0:
        return None
    return {k: round(v / tot, 6) for k, v in filtered.items()}


def alpha_power(probs, alpha):
    """Ridistribuisce probabilità con la potenza ``alpha``.

    alpha > 1 enfatizza l'esito più probabile (il modello "seguace del
    favorito"), alpha < 1 lo appiattisce. Il valore ideale si minimizza sul
    Brier dei pronostici storici (come l'OddsComparisonBettor del paper).
    """
    if alpha is None or alpha == 1.0 or not probs:
        return probs
    powered = {k: max(v, 1e-6) ** alpha for k, v in probs.items()
               if isinstance(v, (int, float)) and v > 0}
    tot = sum(powered.values())
    if tot <= 0:
        return probs
    return {k: round(v / tot, 6) for k, v in powered.items()}


def blend(dist_a, dist_b, weight):
    """Fonde due distribuzioni dello stesso mercato col ``weight`` di b.

    Se una manca, ritorna l'altra; altrimenti mescola e rinormalizza.
    """
    if not dist_b:
        return dist_a
    if not dist_a:
        return dist_b
    out = {}
    for k in dist_a:
        b = dist_b.get(k)
        out[k] = (1 - weight) * dist_a[k] + weight * b if b is not None else dist_a[k]
    tot = sum(out.values())
    if tot <= 0:
        return dist_a
    return {k: round(v / tot, 6) for k, v in out.items()}