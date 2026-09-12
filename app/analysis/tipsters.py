"""Mix "AI + tipster": registro affidabilità delle fonti esterne e blend.

Ogni fonte esterna (es. Soccervista) produce per ogni partita i propri
pronostici (1X2, Over/Under 2.5, risultato esatto, confidenza). Teniamo uno
storico di centratura in ``config.TIPSTERS_FILE`` e:

  * un tipster che sbaglia viene pesato meno e, sotto soglia, ESCLUSO
    ("evita quelli che sbagliano");
  * le sue pseudo-probabilità entrano nel mix del predictor con peso
    ``TIPSTER_BLEND_WEIGHT``, insieme al mercato e al nostro modello.

Il punteggio iniziale arriva direttamente dai match già giocati che la fonte
DICHIARA di aver pronosticato (``lastPredictions``): niente attesa, si parte
con una stima reale dell'affidabilità.
"""
import logging

import config
from app.core import kv

log = logging.getLogger("tipsters")

# liste ordinate degli esiti per mercato (come nelle chiavi del predictor)
OUT_MAP = {
    "1x2": ("1", "x", "2"),
    "over_under": ("over_2.5", "under_2.5"),
    "btts": ("si", "no"),
}


def _norm_outcome(o):
    o = str(o or "").upper()
    if o in ("1", "X", "2"):
        return {"1": "1", "X": "x", "2": "2"}[o]
    return None


def _norm_goals(g):
    g = str(g or "").upper()
    if g == "O":
        return "over_2.5"
    if g == "U":
        return "under_2.5"
    return None


def load():
    data = kv.read_json("tipsters.json")
    if not isinstance(data, dict):
        data = {}
    data.setdefault("sources", {})
    return data


def save(data):
    kv.write_json("tipsters.json", data)


def _source(data, name):
    src = data["sources"].setdefault(name, {
        "total": 0, "hits": 0, "rate": None,
        "by_market": {}, "banked_ids": [], "last": [],
    })
    src.setdefault("by_market", {})
    src.setdefault("banked_ids", [])
    src.setdefault("last", [])
    return src


def _hit(src, market, hit):
    st = src["by_market"].setdefault(market, {"total": 0, "hits": 0})
    st["total"] += 1
    st["hits"] += int(bool(hit))
    src["total"] += 1
    src["hits"] += int(bool(hit))
    src["rate"] = round(src["hits"] / src["total"], 3)


# --------------------------------------------------------------- bank
def bank(src_name, last_events):
    """Inserisce nello storico le previsioni GIÀ GIOCATE (retroattive)."""
    data = load()
    src = _source(data, src_name)
    added = 0
    for e in last_events or []:
        eid = e.get("id")
        if not eid or eid in src["banked_ids"]:
            continue
        final = e.get("final")
        if not final:
            continue
        hs, as_ = final["home_score"], final["away_score"]
        real = {"1x2": _result_1x2(hs, as_), "over_under": _result_ou(hs, as_),
                "btts": _result_btts(hs, as_)}
        out = _norm_outcome(e.get("outcome"))
        if out is not None:
            _hit(src, "1x2", out == real["1x2"])
        goals = _norm_goals(e.get("goals"))
        if goals is not None:
            _hit(src, "over_under", goals == real["over_under"])
        sc = e.get("score")
        if sc and isinstance(sc, str) and ":" in sc:
            src["by_market"].setdefault("score", {"total": 0, "hits": 0})
            sm = src["by_market"]["score"]
            sm["total"] += 1
            sm["hits"] += int(sc == f"{hs}:{as_}")
        src["last"].append({"home": e.get("home"), "away": e.get("away"),
                            "score": f"{final['home_score']}-{final['away_score']}",
                            "outcome": e.get("outcome"), "pred": e.get("score")})
        src["last"] = src["last"][-30:]
        src["banked_ids"].append(eid)
        src["banked_ids"] = src["banked_ids"][-80:]
        added += 1
    if added:
        save(data)
        log.info("tipster %s: +%d previsioni già giocate (rate %.0f%%)",
                 src_name, added, (src["rate"] or 0) * 100)
    return src


# ------------------------------------------------------------ collect
def collect(fixtures, provider=None):
    """Recupera i pronostici esterni per le prossime partite e li aggancia."""
    from app.sources import soccervista as sv
    client = provider or sv.SoccervistaClient()
    try:
        feed = client.fetch_serie_a()
    except Exception as e:
        log.debug("tipster fetch fallito: %s", e)
        return None
    src = bank("soccervista", feed.get("last") or [])
    attached = 0
    for fx in fixtures:
        ev = sv.map_to_fixture(feed.get("next") or [], fx)
        if not ev:
            continue
        picks = {
            "outcome": ev.get("outcome"),
            "goals": ev.get("goals"),
            "score": ev.get("score"),
            "conf": ev.get("conf"),
        }
        fx.predictions.setdefault("tipsters", {})["soccervista"] = picks
        fx.predictions["tipster_meta"] = {
            "name": "Soccervista",
            "rate": src.get("rate"),
            "samples": src.get("total"),
        }
        attached += 1
    if attached:
        log.info("tipster: %d partite abbinate a Soccervista", attached)
    return feed


# ------------------------------------------------------------ evaluate
def evaluate():
    """Valuta i pronostici esterni delle partite ormai concluse."""
    learning = kv.read_json("learning.json") or {"records": []}
    data = load()
    changed = False
    for r in learning.get("records") or []:
        if r.get("tipsters_evaluated") or not r.get("evaluated"):
            continue
        tips = r.get("tipsters")
        res = r.get("result")
        if not tips or not res:
            continue
        for src_name, picks in tips.items():
            src = _source(data, src_name)
            out = _norm_outcome(picks.get("outcome"))
            if out is not None:
                _hit(src, "1x2", out == res.get("1x2"))
            goals = _norm_goals(picks.get("goals"))
            if goals is not None:
                _hit(src, "over_under", goals == res.get("over_under"))
            sc = picks.get("score")
            if sc and isinstance(sc, str) and ":" in sc:
                src["by_market"].setdefault("score", {"total": 0, "hits": 0})
                sm = src["by_market"]["score"]
                sm["total"] += 1
                sm["hits"] += int(sc == f"{res['home_score']}:{res['away_score']}")
        r["tipsters_evaluated"] = True
        changed = True
    if changed:
        save(data)
    return data


# ------------------------------------------------------------- blend
def trusted(data, src_name):
    """Un tipster è fidato solo se ha abbastanza campioni e sbaglia poco."""
    src = (data.get("sources") or {}).get(src_name) or {}
    if not (src.get("total") or 0) >= config.TIPSTER_MIN_SAMPLES:
        return False
    rate = src.get("rate") or 0
    return rate >= config.TIPSTER_MIN_ACCURACY


def _belief(src, conf):
    base = config.TIPSTER_BASE_CONF + (conf or 0) * config.TIPSTER_CONF_PER_POINT
    base = min(0.95, base)
    rate = min(1.0, (src.get("rate") or 0) + 0.05)  # leggera fiducia di default
    return (base - 0.5) * rate + 0.5


def tipster_distribution(market, model_probs, picks, data, src_name):
    """Distribuzione pseudo-prob del tipster per un mercato (None se non fidato)."""
    if not trusted(data, src_name):
        return None
    src = (data.get("sources") or {}).get(src_name) or {}
    keys = OUT_MAP[market]
    pick = None
    if market == "1x2":
        pick = _norm_outcome(picks.get("outcome"))
    elif market == "over_under":
        pick = _norm_goals(picks.get("goals"))
    elif market == "btts":
        pick = {"si": "si", "no": "no"}.get(str(picks.get("btts") or "").lower())
    if pick not in keys:
        return None
    belief = _belief(src, picks.get("conf"))
    # agli altri esiti tocca il resto, ripartito come dal modello
    rest = 1.0 - belief
    rest_sum = sum(model_probs.get(k, 0) for k in keys if k != pick) or 1.0
    out = {}
    for k in keys:
        if k == pick:
            out[k] = belief
        else:
            out[k] = rest * (model_probs.get(k, 0) / rest_sum)
    tot = sum(out.values())
    return {k: (v / tot if tot else 0) for k, v in out.items()} if tot else None


def blend(probs, picks, data, src_name):
    """Fonde i mercati 1X2/O-U con la voce esterna, poi rinormalizza."""
    if not picks:
        return probs, False
    applied = False
    for market in ("1x2", "over_under"):
        pm = probs.get(market) or {}
        if not pm:
            continue
        dist = tipster_distribution(market, pm, picks, data, src_name)
        if not dist:
            continue
        w = config.TIPSTER_BLEND_WEIGHT
        merged = {k: (1 - w) * pm[k] + w * dist[k] for k in pm}
        tot = sum(merged.values())
        if tot > 0:
            probs[market] = {k: round(v / tot, 4) for k, v in merged.items()}
            applied = True
    return probs, applied


# ------------------------------------------------------------ helpers
def _result_1x2(h, a):
    return "1" if h > a else ("2" if h < a else "x")


def _result_ou(h, a):
    return "over_2.5" if h + a > 2.5 else "under_2.5"


def _result_btts(h, a):
    return "si" if h > 0 and a > 0 else "no"