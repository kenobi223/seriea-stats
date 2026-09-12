"""Modello del mercato: "le quote come feature", calibrate out-of-sample.

Le probabilità implicite de-juicate delle quote non sono la probabilità vera:
di solito sopravvalutano i favoriti e sottovalutano gli sfavoriti. Questo
modulo apprende, per ogni mercato (1x2/over_under/btts), un esponente
``alpha`` tale che ``p_estimata = p_implicita ** alpha`` (rinormalizzato)
minimizzi il Brier **out-of-sample** sui pronostici storici.

Procedura walk-forward (nessuna informazione futura):
per ogni pronostico valutato si sceglie l'alpha SOLO dai record precedenti
(round anteriori e partite finite prima), lo si applica al record corrente e
si accumula l'errore OOS. L'alpha di produzione è quello scelto per l'ultimo
pronostico (l'informazione più recente).

L'approccio è quello dell'articolo "Beating the bookies with their own
numbers" (arXiv:1710.02824), adattato al consenso di odds centralizzato.
"""
import logging
import time

import config
from app.core import kv, markets

log = logging.getLogger("market_model")

ALPHA_GRID = [round(0.60 + 0.05 * i, 2) for i in range(17)]  # 0.60 ... 1.40
MIN_SAMPLES = 3   # record precedenti per scegliere un alpha significativo


def load():
    data = kv.read_json("market_alpha.json")
    return data if isinstance(data, dict) else {}


def save(data):
    kv.write_json("market_alpha.json", data)


def alphas():
    """{mercato: alpha} attualmente in produzione (per il predictor)."""
    return {m: (d or {}).get("alpha") for m, d in load().items()}


def estimate(market_prob, alpha):
    """Probabilità di mercato calibrate col modello (``p**alpha``)."""
    return markets.alpha_power(market_prob, alpha)


# ------------------------------------------------------------- fit
def _brier_for(alpha, market, keys, recs):
    """Brier medio applicando ``alpha`` alle quote dei record passati."""
    terms = []
    for r in recs:
        mp = (r.get("market_probs") or {}).get(market)
        if not isinstance(mp, dict):
            continue
        actual = (r.get("result") or {}).get(market)
        dist = markets.alpha_power(mp, alpha)
        for k in keys:
            terms.append((dist.get(k) or 0) - (1 if actual == k else 0))
    return sum(t * t for t in terms) / len(terms) if terms else None


def _best_alpha(recs, market, keys):
    """L'alpha della griglia con Brier più basso sui record passati."""
    best_a, best_b = None, None
    for a in ALPHA_GRID:
        b = _brier_for(a, market, keys, recs)
        if b is not None and (best_b is None or b < best_b):
            best_a, best_b = a, b
    return best_a or 1.0


def fit():
    """Ricalcola gli alpha per mercato dai pronostici valutati (walk-forward)."""
    learning = kv.read_json("learning.json") or {}
    records = [r for r in learning.get("records") or []
               if r.get("evaluated") and r.get("result")]
    records.sort(key=lambda r: ((r.get("start_ts") or 0) or 0,
                                (r.get("round") or 0)))
    out = {}
    for market, keys in markets.MARKETS.items():
        recs = [r for r in records
                if isinstance((r.get("market_probs") or {}).get(market), dict)]
        if len(recs) < MIN_SAMPLES + 1:
            continue
        chosen = []
        oos_terms = []
        raw_terms = []
        for i, r in enumerate(recs):
            r_round = r.get("round") or 0
            r_ts = r.get("start_ts") or 0
            prior = [x for x in recs[:i]
                     if (x.get("round") or 0) < r_round
                     and (not r_ts or (x.get("start_ts") or 0) < r_ts)]
            if len(prior) < MIN_SAMPLES:
                continue
            a = _best_alpha(prior, market, keys)
            chosen.append(a)
            mp = r["market_probs"][market]
            actual = (r.get("result") or {}).get(market)
            dist = markets.alpha_power(mp, a)
            for k in keys:
                oos_terms.append((dist.get(k) or 0) - (1 if actual == k else 0))
                raw_terms.append((mp.get(k) or 0) - (1 if actual == k else 0))
        if not oos_terms:
            continue
        oos_brier = round(sum(t * t for t in oos_terms) / len(oos_terms), 4)
        raw_brier = round(sum(t * t for t in raw_terms) / len(raw_terms), 4)
        prod = chosen[-1] if chosen else 1.0
        out[market] = {
            "alpha": prod,
            "n": len(recs),
            "oos_brier": oos_brier,
            "raw_brier": raw_brier,
            "better": oos_brier <= raw_brier,
            "last_chosen": chosen[-5:],
            "updated": int(time.time()),
        }
        log.info("market_model %s: alpha %.2f (Brier OOS %.3f vs raw %.3f)",
                 market, prod, oos_brier, raw_brier)
    if out:
        data = load()
        data.update(out)
        save(data)
    return out