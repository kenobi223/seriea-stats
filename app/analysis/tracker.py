"""Autocritica e auto-correzione del modello pronostici.

Ciclo:
  1. record()      salva in modo persistente ogni pronostico emesso (con le sue
                   probabilità, i best_bet e le quote) prima che la partita
                   venga giocata;
  2. evaluate()    a partita finita recupera il risultato reale e segna ogni
                   pronostico come indovinato o sbagliato;
  3. analyze()     confronta probabilità predette vs esiti reali (calibrazione),
                   calcola tasso di centratura, Brier score e cosa ha imparato;
                   produce i correttori usati dal predictor per diventare più
                   onesto;
  4. walk_forward() backtest fuori campione: verifica onestà applicando la
                   calibrazione SOLO sui pronostici precedenti a ciascuno
                   (nessuna informazione futura = "sarebbe valsa anche prima?").

I dati persistono in ``config.LEARNING_FILE`` (JSON), separati dallo stato di
gioco per non appesantire ``state.json``.
"""
import logging
import random
import threading

import config
from app.core import kv

log = logging.getLogger("tracker")

# serializza le operazioni load-modifica-save (record/evaluate/analyze/walk_forward):
# lo scheduler e il monitor live girano in thread separati e possono valutare
# partite finite contemporaneamente senza perdere aggiornamenti.
_lock = threading.RLock()


def _sync(fn):
    """Avvolge una funzione che modifica la memoria dello storico col lock."""
    def wrapped(*args, **kwargs):
        with _lock:
            return fn(*args, **kwargs)
    return wrapped


MIN_SAMPLES = config.TRACKING_MIN_SAMPLES
MAX_RECORDS = config.MAX_TRACKED
CLAMP = (config.CALIBRATION_CLAMP_LO, config.CALIBRATION_CLAMP_HI)

# mercato -> i suoi esiti ("pick" come nelle probs del predictor)
MARKETS = {
    "1x2": ("1", "x", "2"),
    "over_under": ("over_2.5", "under_2.5"),
    "btts": ("si", "no"),
}


def _rps(probs, actual_key):
    """Ranked Probability Score per un mercato ordinale (qui 1X2).

    0 = perfetto, 1 = peggiore. A differenza del Brier rispetta l'ordinalita':
    sbagliare tra "1" e "2" pesa piu di sbagliare tra "1" e "x".
    """
    cpred = ctrue = 0.0
    total = 0.0
    ordered = ("1", "x", "2")
    if not probs:
        return None
    for k in ordered[:-1]:
        cpred += probs.get(k, 0.0)
        ctrue += 1 if actual_key == k else 0
        total += (cpred - ctrue) ** 2
    return total / (len(ordered) - 1)


def _bootstrap_ci(pairs, seed=7, n=2000):
    """Bootstrap paired (per record) sulla differenza di MSE OOS.

    pairs: lista di (mse_prima, mse_dopo). Ritorna l'intervallo di confidenza
    al 95% della differenza attesa (prima - dopo): se 'lo' > 0 l'autocorrezione
    migliora davvero fuori campione e non per caso. Seed fisso = riproducibile.
    """
    if len(pairs) < 3:
        return None
    rng = random.Random(seed)
    k = len(pairs)
    diffs = []
    for _ in range(n):
        b = a = 0.0
        for _ in range(k):
            bi, ai = pairs[rng.randrange(k)]
            b += bi
            a += ai
        diffs.append((b - a) / k)
    diffs.sort()
    lo = diffs[int(n * 0.025)]
    hi = diffs[int(n * 0.975)]
    p_better = 1.0 - sum(1 for d in diffs if d <= 0) / n
    return {"lo": round(lo, 4), "hi": round(hi, 4), "p_better": round(p_better, 3),
            "significant": lo > 0}

# label esito dei pronostici "best_bets" -> (mercato, key probs)
def _bet_market_key(pick):
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


def _outcome(home, away):
    """Esito 1x2 / over / btts reali a partire dal punteggio."""
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


def _saves_outcome(record, client):
    """Confronta i pick sulle parate coi numeri reali (esito per lato).

    Un pick "over 2.5 parate" è centrato se le parate reali del portiere
    (dalla statistica squadra della partita) sono >= soglia.
    """
    picks = record.get("saves_picks") or []
    if not picks:
        return None
    try:
        stats = client._cached(f"stats-{record['id']}",
                               lambda: client.statistics(record["id"]))
    except Exception as e:
        log.debug("saves outcome %s: %s", record.get("id"), e)
        return None
    if not stats:
        return None
    out = {}
    for p in picks:
        side = p.get("side")
        block = (stats.get(side) or {})
        actual = block.get("goalkeeper_saves")
        if actual is None:
            actual = block.get("total_saves")
        if actual is None:
            continue
        try:
            actual = int(actual)
        except (TypeError, ValueError):
            continue
        thr = p.get("threshold") or 3.0
        out[side] = {"team": p.get("team"), "gk": p.get("gk"),
                     "pick": p.get("pick"), "threshold": thr,
                     "actual": actual,
                     "hit": int(actual >= thr)}
    return out or None


def _clamp(v):
    return max(CLAMP[0], min(CLAMP[1], v))


# ------------------------------------------------------------------- file
def load():
    data = kv.read_json("learning.json")
    if not isinstance(data, dict):
        data = {}
    data.setdefault("records", [])
    data.setdefault("tracking", {})
    data.setdefault("calibration", {})
    return data


def save(data):
    kv.write_json("learning.json", data)


# ----------------------------------------------------------------- record
def _fx_fields(fx):
    """Normalizza un fixture (oggetto dataclass o dict) in campi semplici."""
    if hasattr(fx, "predictions"):
        return (fx.id, fx.home, fx.away, fx.start_ts, fx.round,
                fx.predictions or {})
    return (fx.get("id"), fx.get("home"), fx.get("away"), fx.get("start_ts"),
            fx.get("round"), (fx.get("predictions") or {}))


@_sync
def record(fixtures):
    """Salva i pronostici correnti (non ancora giocati) nello storico.

    Accetta anche i fixture ``finished`` rimasti nello stato di un'esecuzione
    precedente: così le partite giocate mentre il programma era spento non
    perdono il proprio pronostico e possono essere valutate comunque.
    """
    data = load()
    known = {r["id"] for r in data["records"]}
    now = __import__("time").time()
    added = 0
    for fx in fixtures:
        fxid, home, away, start_ts, rnd, preds = _fx_fields(fx)
        if fxid in known:
            continue
        if not (preds or {}).get("1x2"):
            continue
        bets = []
        for b in (preds.get("best_bets") or [])[:3]:
            mkk = _bet_market_key(b.get("pick"))
            if not mkk:
                continue
            bets.append({"market": mkk[0], "pick": mkk[1],
                         "prob": b.get("prob"), "odds": b.get("odds"),
                         "edge": b.get("edge")})
        picks = []
        for market, mp in (preds.get("model_picks") or {}).items():
            if not mp or not mp.get("key"):
                continue
            picks.append({"market": market, "pick": mp["key"],
                          "prob": mp.get("prob"), "odds": mp.get("odds"),
                          "conf": mp.get("conf")})
        saves_picks = []
        for side in ("home", "away"):
            sb = (getattr(fx, "keeper_saves", {}) or {}).get(side)
            if sb and sb.get("pick"):
                saves_picks.append({
                    "side": side, "team": sb.get("team"),
                    "pick": sb.get("pick"), "gk": sb.get("gk"),
                    "threshold": sb.get("threshold"),
                    "prob": sb.get("over_prob"),
                    "fair": sb.get("fair_over"),
                    "expected": sb.get("expected"),
                    "played": sb.get("played"),
                })
        data["records"].append({
            "id": fxid, "home": home, "away": away,
            "start_ts": start_ts or 0, "round": rnd,
            "recorded_at": int(now),
            "probs": {m: preds.get(m, {}) for m in MARKETS},
            "market_probs": preds.get("market_probs") or {},
            "bets": bets,
            "picks": picks,
            "saves_picks": saves_picks,
            "tipsters": preds.get("tipsters"),
            "evaluated": False, "result": None,
            "tipsters_evaluated": False,
        })
        known.add(fxid)
        added += 1

    # mantiene i più recenti ma non butta mai quelli non ancora valutati
    data["records"] = sorted(data["records"],
                             key=lambda r: (r.get("evaluated"), -(r.get("start_ts") or 0)))
    if len(data["records"]) > MAX_RECORDS:
        data["records"] = data["records"][:MAX_RECORDS]
    if added:
        save(data)
        log.info("registrationi: +%d pronostici salvati (totale %d)",
                 added, len(data["records"]))


# --------------------------------------------------------------- evaluate
@_sync
def evaluate(client, force_ids=None):
    """Controlla le partite non ancora valutate e scrive l'esito reale.

    ``force_ids`` (lista di fixture id) fa valutare subito quelle partite già
    confermate "finished" dal monitor live, saltando l'attesa di sicurezza.
    """
    data = load()
    changed = 0
    now = __import__("time").time()
    delay = config.TRACKING_EVAL_DELAY_HOURS * 3600
    force = set(force_ids or ())
    for r in data["records"]:
        if r.get("evaluated") or not r.get("id"):
            continue
        # la partita può essere finita solo ~2.5h dopo il fischio d'inizio
        # (a meno che il live non l'abbia già confermata finita)
        if (r.get("start_ts") or 0) > 0 and now - r["start_ts"] < delay \
                and r["id"] not in force:
            continue
        try:
            detail = client.event_detail(r["id"])
        except Exception as e:
            log.debug("tracker: esito %s non recuperabile: %s", r.get("id"), e)
            continue
        if not detail or detail.get("status") != "finished":
            continue
        hs = detail.get("home_score")
        as_ = detail.get("away_score")
        if hs is None or as_ is None:
            continue
        r["result"] = {"home_score": hs, "away_score": as_,
                       **{m: _outcome(hs, as_)[m] for m in MARKETS}}
        r["saves_result"] = _saves_outcome(r, client)
        r["evaluated"] = True
        r["evaluated_at"] = int(now)
        changed += 1
        log.info("tracker: %s %s-%s %s valutato (%s-%s)",
                 r.get("home"), r.get("away"), r.get("round"), r.get("id"),
                 hs, as_)
    if changed:
        save(data)
        log.info("tracker: %d pronostici valutati a fine partita", changed)
    return changed


# ---------------------------------------------------- avvisi "pronostico ok"
MAX_WIN_AGE = 48 * 3600   # notifica solo pronostici di partite < 48h fa


def pending_wins():
    """Best-bet indovinati a fine partita, non ancora notificati."""
    data = load()
    now = __import__("time").time()
    out = []
    for r in data["records"]:
        if r.get("win_notified") or not r.get("evaluated"):
            continue
        res = r.get("result")
        if not res:
            continue
        start_ts = r.get("start_ts") or 0
        if start_ts and now - start_ts > MAX_WIN_AGE:
            continue
        hits = [b for b in r.get("bets", [])
                if b.get("pick") == res.get(b.get("market"))]
        if not hits:
            continue
        out.append({
            "id": r["id"], "home": r.get("home"), "away": r.get("away"),
            "round": r.get("round"),
            "score": f"{res['home_score']}-{res['away_score']}",
            "hits": [{"market": b["market"], "pick": b["pick"],
                      "prob": b.get("prob"), "odds": b.get("odds")}
                     for b in hits],
        })
    return out


@_sync
def mark_wins_notified(ids):
    """Segna come notificati i pronostici vincenti (evita doppie foto)."""
    ids = set(ids or ())
    if not ids:
        return
    data = load()
    changed = False
    for r in data["records"]:
        if r.get("id") in ids and not r.get("win_notified"):
            r["win_notified"] = True
            changed = True
    if changed:
        save(data)


# ---------------------------------------------------------------- analyze
def _fit_calibration(records):
    """Calibrazione (factor actual/pred per esito) da un set di record valutati.

    Ritorna (calibration, top_picks, brier_in_sample) dove brier_in_sample è
    l'errore quadratico medio delle probabilità originali del set.
    """
    calibration = {m: {} for m in MARKETS}
    picks_stats = {}
    brier_terms = []
    for r in records:
        res = r["result"]
        probs = r.get("probs") or {}
        for m, mkeys in MARKETS.items():
            pm = probs.get(m) or {}
            for k in mkeys:
                p = pm.get(k)
                if not isinstance(p, (int, float)) or p <= 0:
                    continue
                hit = 1 if res.get(m) == k else 0
                brier_terms.append(p - hit)
                s = picks_stats.setdefault((m, k), {"pred": 0.0, "hit": 0, "n": 0})
                s["pred"] += p
                s["hit"] += hit
                s["n"] += 1
    brier = (round(sum(t * t for t in brier_terms) / len(brier_terms), 4)
             if brier_terms else None)

    top_picks = []
    for (m, k), s in picks_stats.items():
        mean_pred = s["pred"] / s["n"]
        actual = s["hit"] / s["n"]
        factor = None
        if s["n"] >= MIN_SAMPLES and mean_pred > 0.02:
            factor = round(_clamp(actual / mean_pred), 3)
            calibration[m][k] = factor
        top_picks.append({"market": m, "pick": k, "count": s["n"],
                          "pred": round(mean_pred, 3), "actual": round(actual, 3),
                          "factor": factor})
    return calibration, top_picks, brier


def _correct(probs, factors):
    """Applica i fattori di calibrazione a una distribuzione e rinormalizza."""
    if not factors:
        return probs
    scaled = {}
    for k, p in probs.items():
        f = factors.get(k, 1.0)
        scaled[k] = _clamp(p * f)
    tot = sum(scaled.values())
    if tot <= 0:
        return probs
    return {k: round(v / tot, 4) for k, v in scaled.items()}


def _prior_records(records, r, round_num=None, start_ts=None):
    """Record precedenti a ``r`` (informazione disponibile PRIMA della partita).

    Usa round < (e, se noto, start_ts <) per non "vedere" partite giocate dopo.
    """
    r_round = round_num if round_num is not None else (r.get("round") or 0)
    r_ts = start_ts if start_ts is not None else (r.get("start_ts") or 0)
    prior = []
    for x in records:
        if x is r:
            continue
        if (x.get("round") or 0) >= r_round:
            continue
        if r_ts and (x.get("start_ts") or 0) >= r_ts:
            continue
        prior.append(x)
    return prior


def calibration_for(round_num, start_ts=None):
    """Calibrazione per il round corrente, SOLO dai round precedenti.

    È il blocco "nessuna fuga di dati avanti": i pronostici della giornata in
    corso (o futura) non calibrano mai quelli stessi.
    """
    data = load()
    records = [x for x in data["records"]
               if x.get("evaluated") and x.get("result")]
    prior = _prior_records(records, {}, round_num=round_num, start_ts=start_ts)
    calibration, _top, _brier = _fit_calibration(prior)
    return calibration


@_sync
def walk_forward():
    """Backtest fuori campione (walk-forward) del processo di calibrazione.

    Per ogni pronostico valutato si ricostruiscono i fattori SOLO dai
    pronostici precedenti (round precedenti e partite finite prima), si
    applicano alle probabilità emesse e si misura l'onestà raggiunta:

      * Brier "prima" (probabilità pubblicate) vs "dopo" (ri-calibrate);
      * tasso di centratura di pronostici/pick/parate in modalità OOS.

    La differenza dice se l'autocorrezione vale davvero out-of-sample o se
    il modello si stava "allenando" sui risultati che andava a prevedere.
    """
    data = load()
    records = sorted([x for x in data["records"]
                      if x.get("evaluated") and x.get("result")],
                     key=lambda x: (x.get("start_ts") or 0) or 0)
    before_terms, after_terms = [], []
    pairs = []
    rps_before, rps_after = [], []
    n_calibrated = 0
    for i, r in enumerate(records):
        prior = _prior_records(records, r)
        factors, _top, _brier = _fit_calibration(prior)
        probs = r.get("probs") or {}
        res = r["result"]
        corrected = {m: _correct(probs.get(m) or {}, factors.get(m) or {})
                     for m in MARKETS}
        corrected_any = any(factors.get(m, {}).get(k) is not None
                            for m in MARKETS for k in (factors.get(m) or {}))
        rec_b, rec_a = [], []
        for m, mkeys in MARKETS.items():
            pm = probs.get(m) or {}
            cm = corrected[m] or {}
            real = res.get(m)
            for k in mkeys:
                p = pm.get(k)
                if not isinstance(p, (int, float)) or p <= 0:
                    continue
                hit = 1 if real == k else 0
                rec_b.append(p - hit)
                after_p = cm.get(k)
                if isinstance(after_p, (int, float)) and after_p > 0:
                    rec_a.append(after_p - hit)
        before_terms.extend(rec_b)
        pm12 = probs.get("1x2")
        real12 = res.get("1x2")
        if pm12 and real12 in ("1", "x", "2"):
            rps_before.append(_rps(pm12, real12))
            if corrected.get("1x2"):
                rps_after.append(_rps(corrected["1x2"], real12))
        if corrected_any and rec_a:
            n_calibrated += 1
            after_terms.extend(rec_a)
            pairs.append((sum(t * t for t in rec_b) / len(rec_b),
                          sum(t * t for t in rec_a) / len(rec_a)))
        # accorcio i primi record (prima non c'era storia da usare): non
        # devono guastare la media OOS, che misura il processo a regime.
    before_brier = (round(sum(t * t for t in before_terms) / len(before_terms), 4)
                    if before_terms else None)
    after_brier = (round(sum(t * t for t in after_terms) / len(after_terms), 4)
                   if after_terms else None)
    ci95 = _bootstrap_ci(pairs)

    oos = {"rounds": len(records),
           "records": len(records),
           "brier": before_brier,
           "brier_calibrated": after_brier,
           "improvement": (round(before_brier - after_brier, 4)
                           if before_brier is not None and after_brier is not None
                           else None),
           "ci95": ci95,
           "significant": bool(ci95 and ci95["significant"]),
           "rps": (round(sum(rps_before) / len(rps_before), 4) if rps_before else None),
           "rps_calibrated": (round(sum(rps_after) / len(rps_after), 4) if rps_after else None),
           "n_calibrated": n_calibrated,
           "reliable": (after_brier is not None and before_brier is not None
                        and after_brier < before_brier),
           "check": _oos_bet_stats(records)}
    data["tracking"] = (data.get("tracking") or {})
    data["tracking"]["oos"] = oos
    save(data)
    return oos


def _oos_bet_stats(records):
    """Centratura OOS di pronostici/pick/parate (solo con storia precedente)."""
    stats = {"bets": {"total": 0, "hit": 0, "rate": None},
             "picks": {"total": 0, "hit": 0, "rate": None},
             "saves": {"total": 0, "hit": 0, "rate": None}}
    for r in records:
        prior = _prior_records(records, r)
        if not prior:
            continue
        res = r["result"]
        for b in r.get("bets", []):
            mkt = b.get("market")
            if mkt in MARKETS and mkt in res:
                stats["bets"]["total"] += 1
                stats["bets"]["hit"] += int(b.get("pick") == res[mkt])
        for pi in r.get("picks", []):
            mkt = pi.get("market")
            if mkt in MARKETS and mkt in res:
                stats["picks"]["total"] += 1
                stats["picks"]["hit"] += int(pi.get("pick") == res[mkt])
        for rec in (r.get("saves_result") or {}).values():
            stats["saves"]["total"] += 1
            stats["saves"]["hit"] += int(bool(rec.get("hit")))
    for k in stats:
        if stats[k]["total"]:
            stats[k]["rate"] = round(stats[k]["hit"] / stats[k]["total"], 3)
    return stats


@_sync
def analyze():
    """Statistiche di centratura + correttori di calibrazione.

    Ritorna (tracking, calibration) e li salva nello storico.
    """
    data = load()
    records = [r for r in data["records"] if r.get("evaluated") and r.get("result")]

    tracking = {"last_updated": int(__import__("time").time()),
                "records": len(data["records"]),
                "evaluated": len(records)}

    # ---- centratura dei pronostici suggeriti (best_bets)
    bets_total = bets_hit = 0
    by_market = {m: {"bets_total": 0, "bets_hit": 0, "bets_rate": None}
                 for m in MARKETS}
    for r in records:
        res = r["result"]
        for b in r.get("bets", []):
            mkt = b.get("market")
            if mkt not in by_market or mkt not in res:
                continue
            hit = 1 if b.get("pick") == res[mkt] else 0
            bets_total += 1
            bets_hit += hit
            by_market[mkt]["bets_total"] += 1
            by_market[mkt]["bets_hit"] += hit
    tracking["bets_total"] = bets_total
    tracking["bets_hit"] = bets_hit
    tracking["bets_rate"] = (bets_hit / bets_total
                             if bets_total else None)
    for m, st in by_market.items():
        st["bets_rate"] = (st["bets_hit"] / st["bets_total"]
                           if st["bets_total"] else None)
    tracking["by_market"] = by_market

    # ---- quante PARTITE hanno visto andare a segno un best-bet (conteggio
    #      per partita: azzeccata se almeno uno dei best-bet era centrato).
    #      affianca il conteggio per pronostico (bets_total), più intuitivo
    #      quando una partita aveva più best-bet.
    match_bets_total = match_bets_hit = 0
    for r in records:
        res = r["result"]
        bets = [b for b in r.get("bets", []) if b.get("market") in res]
        if not bets:
            continue
        match_bets_total += 1
        if any(b.get("pick") == res[b.get("market")] for b in bets):
            match_bets_hit += 1
    tracking["match_bets_total"] = match_bets_total
    tracking["match_bets_hit"] = match_bets_hit
    tracking["match_bets_rate"] = (match_bets_hit / match_bets_total
                                   if match_bets_total else None)

    # ---- centratura dei pick del MODELLO (il pronostico che emettiamo per
    #      ogni mercato, indipendente dalla quota/valore)
    picks_total = picks_hit = 0
    picks_by_market = {m: {"picks_total": 0, "picks_hit": 0, "picks_rate": None}
                       for m in MARKETS}
    for r in records:
        res = r["result"]
        for pi in r.get("picks", []):
            mkt = pi.get("market")
            if mkt not in picks_by_market or mkt not in res:
                continue
            hit = 1 if pi.get("pick") == res[mkt] else 0
            picks_total += 1
            picks_hit += hit
            picks_by_market[mkt]["picks_total"] += 1
            picks_by_market[mkt]["picks_hit"] += hit
    tracking["picks_total"] = picks_total
    tracking["picks_hit"] = picks_hit
    tracking["picks_rate"] = (picks_hit / picks_total if picks_total else None)
    for m, st in picks_by_market.items():
        st["picks_rate"] = (st["picks_hit"] / st["picks_total"]
                            if st["picks_total"] else None)
    tracking["picks_by_market"] = picks_by_market

    # ---- partite in cui il pick del modello (1x2/over/BTTS) è centrato
    match_picks_total = match_picks_hit = 0
    for r in records:
        res = r["result"]
        pks = [pi for pi in r.get("picks", []) if pi.get("market") in res]
        if not pks:
            continue
        match_picks_total += 1
        if any(pi.get("pick") == res[pi.get("market")] for pi in pks):
            match_picks_hit += 1
    tracking["match_picks_total"] = match_picks_total
    tracking["match_picks_hit"] = match_picks_hit
    tracking["match_picks_rate"] = (match_picks_hit / match_picks_total
                                    if match_picks_total else None)

    # ---- centratura dei pronostici sulle parate dei portieri
    saves_total = saves_hit = 0
    for r in records:
        sr = r.get("saves_result") or {}
        for rec in sr.values():
            saves_total += 1
            saves_hit += int(bool(rec.get("hit")))
    tracking["saves_total"] = saves_total
    tracking["saves_hit"] = saves_hit
    tracking["saves_rate"] = (saves_hit / saves_total if saves_total else None)

    # ---- calibrazione: probabilità predetta vs esito reale per ogni esito
    calibration, top_picks, brier = _fit_calibration(records)
    tracking["brier"] = brier
    tracking["top_picks"] = top_picks

    # ---- RPS (Ranked Probability Score) sul 1X2: onestà ordinale. A parità
    #      di Brier, sbagliare "1" quando usciva "2" deve pesare più di "x".
    rps_vals = []
    for r in records:
        pm = (r.get("probs") or {}).get("1x2")
        if not pm or {"1", "x", "2"}.isdisjoint(pm):
            continue
        real = (r.get("result") or {}).get("1x2")
        if real in ("1", "x", "2"):
            rps_vals.append(_rps(pm, real))
    tracking["rps"] = (round(sum(rps_vals) / len(rps_vals), 4) if rps_vals else None)

    # ---- onestà per fasce di probabilità (0-20%,20-40%,...)
    binned = [(p, hit) for r in records for (p, hit) in _pick_rows(r)]
    edges = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    bins = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        vals = [v for v in binned if lo <= v[0] < hi]
        pred = sum(v[0] for v in vals) / len(vals) if vals else None
        actual = sum(v[1] for v in vals) / len(vals) if vals else None
        bins.append({"lo": lo, "hi": hi, "count": len(vals),
                     "pred": round(pred, 3) if pred is not None else None,
                     "actual": round(actual, 3) if actual is not None else None})
    tracking["calibration_bins"] = bins

    # ---- errori più clamorosi (il modello era convinto ed ha sbagliato)
    misses = []
    for r in records:
        res = r["result"]
        for b in r.get("bets", []):
            if b.get("pick") == res.get(b.get("market")):
                continue
            misses.append({"home": r.get("home"), "away": r.get("away"),
                           "round": r.get("round"), "score":
                               f"{res['home_score']}-{res['away_score']}",
                           "pick": b.get("pick"), "prob": b.get("prob"),
                           "odds": b.get("odds"), "market": b.get("market")})
    misses.sort(key=lambda m: m.get("prob") or 0, reverse=True)
    tracking["notable_misses"] = misses[:8]

    # ---- cosa ho imparato (in italiano)
    conclusions = []
    if tracking["bets_rate"] is not None:
        conclusions.append(
            f"Ho indovinato {tracking['bets_hit']} pronostici su "
            f"{tracking['bets_total']} valutati "
            f"({tracking['bets_rate'] * 100:.0f}%).")
    lbl = {"1x2": "risultato 1X2", "over_under": "Over/Under 2.5",
           "btts": "entrambe le squadre a segno"}
    for m in MARKETS:
        st = by_market[m]
        if not st["bets_total"]:
            continue
        conclusions.append(
            f"Nel mercato {lbl[m]} sono {st['bets_hit']}/{st['bets_total']} "
            f"({st['bets_rate'] * 100:.0f}%).")
    for m in MARKETS:
        st = picks_by_market[m]
        if not st["picks_total"]:
            continue
        conclusions.append(
            f"Pronostico modello su {lbl[m]}: {st['picks_hit']}/{st['picks_total']} "
            f"({st['picks_rate'] * 100:.0f}%).")
    if tracking.get("saves_total"):
        conclusions.append(
            f"Parate dei portieri: {tracking['saves_hit']}/{tracking['saves_total']} "
            f"({tracking['saves_rate'] * 100:.0f}%).")
    for tp in top_picks:
        if tp["factor"] is not None:
            per = tp["factor"] * 100
            if per > 100:
                msg = (f"Sull'esito \"{tp['pick']}\" ({lbl[tp['market']]}) il "
                       f"modello in media dava {tp['pred'] * 100:.0f}% ma la "
                       f"realtà dice {tp['actual'] * 100:.0f}%: sottostimo, "
                       f"correggo ×{tp['factor']:.2f}.")
            else:
                msg = (f"Sull'esito \"{tp['pick']}\" ({lbl[tp['market']]}) il "
                       f"modello in media dava {tp['pred'] * 100:.0f}% ma la "
                       f"realtà dice {tp['actual'] * 100:.0f}%: ero troppo "
                       f"ottimista, correggo ×{tp['factor']:.2f}.")
            conclusions.append(msg)
    over_conf = [b for b in bins if b["count"] >= MIN_SAMPLES
                 and b["actual"] is not None and b["pred"] is not None
                 and b["pred"] - b["actual"] >= 0.15]
    if over_conf:
        worst = max(over_conf, key=lambda b: b["pred"] - b["actual"])
        conclusions.append(
            f"Sopravvaluto le probabilità alte: dove dicevo circa "
            f"{worst['pred'] * 100:.0f}% ho centrato solo "
            f"{worst['actual'] * 100:.0f}% delle volte.")
    if tracking["brier"] is not None:
        conclusions.append(
            f"Brier score {tracking['brier']:.3f} (più basso = più onesto).")
    if not conclusions:
        conclusions.append(
            "Nessun pronostico ancora valutato: i dati verranno confrontati "
            "con i risultati reali man mano che le partite si concludono.")
    tracking["conclusions"] = conclusions

    # ---- backtest fuori campione (può dirsi "e se ci fossi già passato?")
    try:
        oos = walk_forward()
        tracking["oos"] = oos
        pod = (oos.get("check") or {}).get("picks") or {}
        if (oos.get("brier_calibrated") is not None
                and oos.get("brier") is not None and oos.get("records", 0) >= 2):
            imp = oos.get("improvement")
            building = f"Fuori campione: con la calibrazione solo sui round " \
                       f"precedenti il Brier passerebbe da {oos['brier']:.3f} " \
                       f"a {oos['brier_calibrated']:.3f}"
            if imp is not None:
                building += f" ({imp:+.3f})"
            ci = oos.get("ci95")
            if ci:
                building += (f"; CI95 {ci['lo']:+.3f}…{ci['hi']:+.3f}, "
                             f"p_better {ci['p_better']:.2f}"
                             + (" (significativo ✅)" if oos.get("significant") else ""))
            if oos.get("rps") is not None:
                rc = oos.get("rps_calibrated") or oos["rps"]
                building += f"; RPS 1X2 {oos['rps']:.3f} → {rc:.3f}"
            if pod.get("total"):
                building += (f"; pronostici OOS {pod['hit']}/{pod['total']} "
                             f"({pod['rate'] * 100:.0f}%)")
            conclusions.append(building + ".")
    except Exception as e:
        log.debug("walk_forward fallito: %s", e)
    tracking["conclusions"] = conclusions

    data["tracking"] = tracking
    data["calibration"] = calibration
    save(data)
    return tracking, calibration


def _pick_rows(record):
    """Per un record valutato, tutte le (prob_predetta, centrato?) dei vari esiti."""
    res = record["result"]
    probs = record.get("probs") or {}
    hit_marks = {m: res.get(m) for m in MARKETS}
    for m, keys in MARKETS.items():
        pm = probs.get(m) or {}
        for k in keys:
            p = pm.get(k)
            if isinstance(p, (int, float)) and p > 0:
                yield p, 1 if hit_marks.get(m) == k else 0


def summary():
    """Riassunto breve per Telegram / assistente."""
    data = load()
    t = data.get("tracking") or {}
    return t