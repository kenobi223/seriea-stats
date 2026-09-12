"""Rilevamento 'errori di quota': disallineamenti tra bookmaker, movimenti
di linea tra i refresh e arbitraggi interni ai mercati."""
import logging
import math

import config
from app.core.models import OddsMove

log = logging.getLogger("value")


def _pct_spread(vals):
    vals = [v for v in vals if v and v > 1]
    if len(vals) < 2:
        return None
    lo, hi = min(vals), max(vals)
    return (hi - lo) / lo, (lo, hi)


def _fixture_label(fx):
    return f"{fx.home} - {fx.away}"


def detect_variables(fixtures):
    """Analizza ogni fixture: spread tra fonti, movimenti, arbitraggi."""
    flags = []
    for fx in fixtures:
        merged = {}
        for o in fx.odds:
            if not o.odds or o.odds <= 1:
                continue
            key = (o.market.lower(), o.pick.lower())
            cur = merged.setdefault(key, {})
            cur[o.source] = o.odds

        # ---- forza tra bookmaker sullo stesso esito
        for (market, pick), values in merged.items():
            spread, (lo, hi) = _pct_spread(list(values.values())) or (None, (None, None))
            if spread is None:
                continue
            if spread >= config.ODD_ERROR_MIN_SPREAD:
                sev = "alert" if spread >= 0.30 else "warn"
                flags.append(OddsMove(fixture=_fixture_label(fx), market=market,
                                      pick=pick, values=values, kind="spread",
                                      message=_spread_msg(_fixture_label(fx), pick, market, values, spread),
                                      severity=sev))

        # ---- movimento di linea tra ultimo snapshot e corrente
        if fx.history:
            prev = {f"{o.source.lower()}/{o.market.lower()}/{o.pick.lower()}": o.odds
                    for o in fx.history[-1]}
            for o in fx.odds:
                key = f"{o.source.lower()}/{o.market.lower()}/{o.pick.lower()}"
                if key in prev and prev[key] and o.odds:
                    delta = (o.odds - prev[key]) / prev[key]
                    if abs(delta) >= config.ODD_MOVE_MIN_PCT:
                        msg = (f"Movimento quote segnalato ULTIMO REFRESH {_fixture_label(fx)} — "
                               f"{o.pick} su {o.source}: {prev[key]} -> {o.odds} "
                               f"({delta*100:+.1f}%)")
                        flags.append(OddsMove(fixture=_fixture_label(fx), market=o.market,
                                              pick=o.pick, values={o.source: o.odds,
                                                                   o.source + " (prec.)": prev[key]},
                                              kind="move", message=msg,
                                              severity="warn"))

        # ---- arbitraggio interno ai mercati complementari
        arb = _find_arb(fx)
        if arb:
            flags.append(arb)

    return flags


def _spread_msg(fixture, pick, market, values, spread):
    best_src = min(values, key=values.get)
    worst_src = max(values, key=values.get)
    return (f"Errore di quota su {fixture} — «{pick}» ({market}): "
            f"{worst_src} {values[worst_src]} contro {best_src} {values[best_src]} "
            f"→ disallineamento {spread*100:.1f}%")


def _find_arb(fx):
    """Somma probabilità implicite dei tre esiti 1/X/2 prendendo la migliore
    quota disponibile per ognuno da qualunque bookmaker."""
    best = {}
    for o in fx.odds:
        if o.market.lower() != "full time":
            continue
        if not o.odds or o.odds <= 1:
            continue
        key = str(o.pick).strip().lower()
        if key not in ("1", "x", "2"):
            continue
        if key not in best or o.odds > best[key][1]:
            best[key] = (o.source, o.odds)
    if len(best) < 3:
        return None
    implied = sum(1.0 / b[1] for b in best.values())
    if implied <= 1.0 - config.ARB_MARGIN:
        msg = (f"Possibile arbitraggio su {_fixture_label(fx)}: 1/{best['1'][1]} + "
               f"1/{best['x'][1]} + 1/{best['2'][1]} = {implied*100:.1f}% "
               f"(margine {1-implied:.1%})")
        values = {k: v[1] for k, v in best.items()}
        return OddsMove(fixture=_fixture_label(fx), market="Full time",
                        pick="arbitraggio 1X2", values=values,
                        kind="arb", message=msg, severity="alert")
    return None