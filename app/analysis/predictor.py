"""Motore pronostici: modello Poisson calibrato su classifica, forma,
casa/trasferta, precedenti e infortuni + motivazioni in italiano."""
import logging
import math

import config
from app.core import markets

log = logging.getLogger("predictor")

MAX_GOALS = 8


def poisson_pmf(lmbda, k):
    return math.exp(-lmbda) * (lmbda ** k) / math.factorial(k)


def _dixon_coles_tau(h, a, lmbda_h, lmbda_a, rho):
    """Correzione tau di Dixon-Coles per i 4 bassi punteggi sistematicamente
    mal stimati dal Poisson indipendente (Dixon & Coles 1997).

    Convenzione: rho<0 rende 0-0 e 1-1 piu probabili e riduce 1-0/0-1.
    Portato da implementation open source (MIT, predicting-ball/penaltyblog)."""
    if h == 0 and a == 0:
        return 1 - lmbda_h * lmbda_a * rho
    if h == 0 and a == 1:
        return 1 + lmbda_h * rho
    if h == 1 and a == 0:
        return 1 + lmbda_a * rho
    if h == 1 and a == 1:
        return 1 - rho
    return 1.0


def _mean(values):
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else 0.0


def _wdl(entries):
    return (sum(1 for e in entries if e.get("result") == "H"),
            sum(1 for e in entries if e.get("result") == "D"),
            sum(1 for e in entries if e.get("result") == "A"))


def _g(entry, idx):
    try:
        return float(entry["score"].split("-")[idx])
    except (KeyError, ValueError, IndexError, AttributeError):
        return None


def _result_pts(entries, for_team=True):
    pts = 0.0
    count = 0
    for e in entries:
        res = e.get("result")
        if res == "H" and for_team:
            pts += 3
        elif res == "A" and not for_team:
            pts += 3
        elif res == "D":
            pts += 1
        count += 1
    return pts, count


def _team_rating(row, league_avg, xg=None, league_xg=None):
    """Attacco e difesa per partita dalla classifica, regolarizzati.

    A inizio stagione il campione è minuscolo (2-4 giornate): le stime grezze
    (gol fatti/subiti a partita) oscillano in modo estremo. Ogni squadra
    "gioca" anche ``REGULARIZATION_PRIOR`` partite virtuali a livello della
    media del campionato, che tirano i valori verso il centro finché il
    campione reale non cresce (shrinkage bayesiano).

    Se i gol attesi (``xg``) sono disponibili, vengono fusi nella valutazione
    (``XG_BLEND_WEIGHT``): lo xG è un segnale meno rumoroso dei gol reali su
    campioni piccoli e rende le lambda del Poisson più stabili. I valori xG
    vengono prima scalati alla media-gol del campionato (la scala degli xG è
    ~simile a quella dei gol ma vanno allineati prima di mescolare).
    """
    gf = row.get("gf") or 0
    ga = row.get("ga") or 0
    played = row.get("played") or 1
    prior = config.REGULARIZATION_PRIOR
    p = max(played, 1)
    att = (gf + league_avg["scored"] * prior) / (p + prior)
    deff = (ga + league_avg["conceded"] * prior) / (p + prior)

    if xg and config.XG_ENABLED:
        xgf = xg.get("xg_for")
        xga = xg.get("xg_ag")
        scale_s = (league_avg["scored"] / league_xg["scored"]
                   if league_xg and league_xg.get("scored") else 1.0)
        scale_c = (league_avg["conceded"] / league_xg["conceded"]
                   if league_xg and league_xg.get("conceded") else 1.0)
        w = config.XG_BLEND_WEIGHT
        if xgf is not None:
            att = (1 - w) * att + w * (xgf * scale_s)
        if xga is not None:
            deff = (1 - w) * deff + w * (xga * scale_c)
    return att, deff


def _split_team_rating(form, side):
    """Attacco e difesa casa/trasferta della squadra dai risultati a parte.

    ``form`` è la forma della squadra (home_results/away_results). Ritorna
    (attacco nella condizione ``side``, difesa nella condizione ``side``)
    oppure (None, None) se il campione manca. ``side`` vale "home"/"away".
    """
    rows = form.get(f"{side}_results") or []
    if not rows:
        return None, None
    gf, ga = [], []
    for r in rows:
        try:
            s = r["score"].split("-")
            if side == "home":
                gf.append(float(s[0]))
                ga.append(float(s[1]))
            else:
                gf.append(float(s[1]))
                ga.append(float(s[0]))
        except (KeyError, ValueError, IndexError):
            continue
    if not gf or not ga:
        return None, None
    return _mean(gf), _mean(ga)


def _blend_split(base, split):
    """Pesa il valore split (casa/trasferta) contro quello generale."""
    if split is None:
        return base
    return (1 - config.HOME_AWAY_SPLIT_WEIGHT) * base + \
        config.HOME_AWAY_SPLIT_WEIGHT * split


def _wmean(values, decay=None):
    """Media pesata per recency: i valori più recenti pesano di più.

    ``decay`` in (0,1] è il fattore di decadimento tra una partita e la
    precedente (il più recente ha peso 1). decay=1 -> media semplice.
    """
    vals = [v for v in values if v is not None]
    if not vals:
        return 0.0
    decay = decay if decay is not None else config.FORM_RECENCY_DECAY
    if decay >= 1:
        return sum(vals) / len(vals)
    wsum = 0.0
    total = 0.0
    for i, v in enumerate(reversed(vals)):
        w = decay ** i
        wsum += v * w
        total += w
    return wsum / total if total else 0.0


def _points_per_game(row):
    """Punti a partita in classifica (misura di forza squadra)."""
    points = row.get("points") or 0
    played = row.get("played") or 1
    return points / played if played else 0.0


def _home_away_avg(form):
    h = form.get("home_results") or []
    a = form.get("away_results") or []
    home_gf = [float(s["score"].split("-")[0]) for s in h if "score" in s]
    away_gf = [float(s["score"].split("-")[1]) for s in a if "score" in s]
    return _mean(home_gf), _mean(away_gf)


def predict_fixture(fx, standings_map, league_avg, calibration=None,
                    tipster_registry=None, team_xg=None, league_xg=None):
    """Ritorna dict predictions per il fixture.

    Se ``calibration`` (dal tracker) è presente, le probabilità vengono
    corrette in base agli errori storici del modello (più oneste) prima di
    calcolare quote fair e migliori giocate. ``team_xg`` è la mappa
    {team_id: tabella xG} di app/analysis/xg.py e ``league_xg`` le corrisp.
    medie di campionato (scala xG ~ scala gol, usate per allineare i numeri).
    """
    home_name, away_name = fx.home, fx.away
    probs = {}

    tipsters = fx.predictions.get("tipsters") or {}
    tip_meta = fx.predictions.get("tipster_meta")

    home_row = standings_map.get(fx.home_id, {})
    away_row = standings_map.get(fx.away_id, {})
    home_att, home_def = _team_rating(home_row, league_avg,
                                      (team_xg or {}).get(fx.home_id),
                                      league_xg)
    away_att, away_def = _team_rating(away_row, league_avg,
                                      (team_xg or {}).get(fx.away_id),
                                      league_xg)

    hf = fx.form_home or {}
    af = fx.form_away or {}

    # ---- split casa/trasferta: quando il campione per condizione esiste,
    #      l'attacco/difesa nella condizione conta di più del dato generale
    home_h_atk, home_h_def = _split_team_rating(hf, "home")
    home_a_atk, home_a_def = _split_team_rating(hf, "away")
    away_h_atk, away_h_def = _split_team_rating(af, "home")
    away_a_atk, away_a_def = _split_team_rating(af, "away")

    # la squadra di casa attacca/difende come "home", quella ospite come "away"
    home_att = _blend_split(home_att, home_h_atk)
    home_def = _blend_split(home_def, home_h_def)
    away_att = _blend_split(away_att, away_a_atk)
    away_def = _blend_split(away_def, away_a_def)

    # gol "sensazione" da forma (ultimi 5, ponderata per recency)
    h_last_5 = [e for e in (hf.get("last_results") or [])][-5:]
    a_last_5 = [e for e in (af.get("last_results") or [])][-5:]
    h_gf5 = _wmean([_g(s, 0) for s in h_last_5 if s.get("home")])
    h_gf5_away = _wmean([_g(s, 0) for s in h_last_5 if not s.get("home")])
    a_gf5 = _wmean([_g(s, 1) for s in a_last_5 if not s.get("home")])
    a_gf5_home = _wmean([_g(s, 1) for s in a_last_5 if s.get("home")])

    # base Poisson semplificato
    h_attack = home_att or league_avg["scored"]
    a_attack = away_att or league_avg["scored"]
    h_def = home_def or league_avg["conceded"]
    a_def = away_def or league_avg["conceded"]

    lmbda_h = (h_attack / league_avg["scored"]) * (a_def / league_avg["conceded"]) * league_avg["home"]
    lmbda_a = (a_attack / league_avg["scored"]) * (h_def / league_avg["conceded"]) * league_avg["away"]

    # aggiustamenti forma
    if h_gf5 and a_gf5 is not None:
        lmbda_h *= clamp(0.8, 1.25, 1 + (h_gf5 - a_def) * 0.03)
    if a_gf5_home is not None and h_gf5_away is not None:
        lmbda_a *= clamp(0.8, 1.25, 1 + (a_gf5_home - h_def) * 0.03)

    # ---- peso della forza dell'avversario
    # Un avversario forte (guardando i punti per partita in classifica) deve
    # rendere meno probabile segnare, uno debole di più. Il risultato contro
    # una squadra forte "vale" di più: qui lo riflettiamo sul gol atteso.
    if config.OPPONENT_STRENGTH_WEIGHT:
        # punti a partita (più alto = squadra più forte)
        home_ppp = _points_per_game(home_row)
        away_ppp = _points_per_game(away_row)
        # quando la squadra è trasferta contro un avversario forte e viceversa
        lmbda_h *= clamp(0.85, 1.15,
                         1 - (away_ppp - home_ppp) * config.OPPONENT_STRENGTH_WEIGHT)
        lmbda_a *= clamp(0.85, 1.15,
                         1 - (home_ppp - away_ppp) * config.OPPONENT_STRENGTH_WEIGHT)

    # h2h leggero
    h2h = fx.h2h or []
    if h2h:
        wh = sum(1 for m in h2h if m.get("winner") == "H")
        wa = sum(1 for m in h2h if m.get("winner") == "A")
        lmbda_h *= clamp(0.9, 1.1, 1 + (wh - wa) * 0.02)
        lmbda_a *= clamp(0.9, 1.1, 1 + (wa - wh) * 0.02)

    # infortuni
    n_inj_h = len(hf.get("injuries") or [])
    n_inj_a = len(af.get("injuries") or [])
    if n_inj_h >= 3:
        lmbda_h *= 0.97
    if n_inj_a >= 3:
        lmbda_a *= 0.97

    # ---- nuovo allenatore ("new manager bounce")
    # Una squadra riorganizzata segna di più e concede di meno: il gol atteso
    # della squadra con nuova guida sale, quello dell'avversario scende.
    ch = fx.coach or {}
    if (ch.get("home") or {}).get("is_new"):
        lmbda_h *= config.NEW_MANAGER_ATTACK_MULT
        lmbda_a *= config.NEW_MANAGER_DEFENSE_MULT
    if (ch.get("away") or {}).get("is_new"):
        lmbda_a *= config.NEW_MANAGER_ATTACK_MULT
        lmbda_h *= config.NEW_MANAGER_DEFENSE_MULT

    probs["lambdas"] = {"home_goals": round(lmbda_h, 3), "away_goals": round(lmbda_a, 3)}

    # ---- digest xG per fixture (dashboard / bot / assistente)
    xg_h = (team_xg or {}).get(fx.home_id) or {}
    xg_a = (team_xg or {}).get(fx.away_id) or {}
    probs["xg"] = {
        "home_for": round(xg_h.get("xg_for") or 0, 2),
        "home_ag": round(xg_h.get("xg_ag") or 0, 2),
        "away_for": round(xg_a.get("xg_for") or 0, 2),
        "away_ag": round(xg_a.get("xg_ag") or 0, 2),
        "played_home": xg_h.get("played"),
        "played_away": xg_a.get("played"),
        "enabled": bool(xg_h and xg_a),
    }

    grid = [[poisson_pmf(lmbda_h, i) * poisson_pmf(lmbda_a, j)
             for j in range(MAX_GOALS)] for i in range(MAX_GOALS)]
    if config.DIXON_COLES_ENABLED:
        for i in range(MAX_GOALS):
            for j in range(MAX_GOALS):
                grid[i][j] *= _dixon_coles_tau(i, j, lmbda_h, lmbda_a,
                                               config.DIXON_COLES_RHO)
    p1 = sum(grid[i][j] for i in range(MAX_GOALS) for j in range(i))          # home vince
    px = sum(grid[i][i] for i in range(MAX_GOALS))
    p2 = sum(grid[i][j] for i in range(MAX_GOALS) for j in range(i + 1, MAX_GOALS))

    tot = p1 + px + p2
    p1, px, p2 = p1 / tot, px / tot, p2 / tot

    p_under_25 = sum(grid[i][j] for i in range(3) for j in range(3 - i))
    p_over_25 = 1 - p_under_25
    p_btts = (1 - math.exp(-lmbda_h)) * (1 - math.exp(-lmbda_a))

    probs["1x2"] = {"1": round(p1, 4), "x": round(px, 4), "2": round(p2, 4)}
    probs["over_under"] = {
        "over_2.5": round(p_over_25, 4),
        "under_2.5": round(p_under_25, 4)}
    probs["btts"] = {"si": round(p_btts, 4), "no": round(1 - p_btts, 4)}

    # ---- auto-correzione dagli errori passati (calibrazione)
    calibrated = False
    if calibration:
        cal1x2 = _apply_cal(probs["1x2"], (calibration.get("1x2") or {}))
        cal_ou = _apply_cal(probs["over_under"], (calibration.get("over_under") or {}))
        cal_b = _apply_cal(probs["btts"], (calibration.get("btts") or {}))
        if cal1x2 is not None or cal_ou is not None or cal_b is not None:
            probs["1x2"] = cal1x2 if cal1x2 is not None else probs["1x2"]
            probs["over_under"] = cal_ou if cal_ou is not None else probs["over_under"]
            probs["btts"] = cal_b if cal_b is not None else probs["btts"]
            calibrated = True

    # ----- risultato esatto (dalla griglia Poisson: più onesto del solo 1X2)
    score_probs = {}
    for i in range(MAX_GOALS):
        for j in range(MAX_GOALS):
            score_probs[f"{i}-{j}"] = grid[i][j]
    top_scores = sorted(score_probs.items(), key=lambda kv: -kv[1])[:config.EXACT_SCORE_TOP]
    probs["exact_score"] = [{"score": s, "prob": round(p, 4)} for s, p in top_scores]

    # ----- mercato: probabilità implicite dalle quote reali (de-juiced).
    #      A inizio stagione il modello è rumoroso: il mercato è un punto di
    #      riferimento molto informato, quindi fondiamo senza però svenderci.
    #      Se il modello mercato (alpha OOS) è attivo, le probabilità
    #      implicite vengono calibrate prima del blend ("odds come feature").
    market = _market_probs(fx)
    if market:
        probs["market_probs"] = {m: mp for m, mp in market.items() if mp}
        alphas = {}
        if config.MARKET_MODEL_ENABLED:
            try:
                from app.analysis import market_model as market_mod
                alphas = market_mod.alphas()
            except Exception as e:
                log.debug("market_model alpha non disponibile: %s", e)
        mixed = {m: (markets.alpha_power(mp, alphas.get(m)) if alphas.get(m)
                     else mp)
                 for m, mp in market.items() if mp}
        probs["1x2"] = _blend_market(probs["1x2"], mixed.get("1x2"))
        probs["over_under"] = _blend_market(probs["over_under"], mixed.get("over_under"))
        probs["btts"] = _blend_market(probs["btts"], mixed.get("btts"))

    # ----- tipster esterno (es. Soccervista): voce nel mix solo se affidabile
    mix = None
    if tipsters and tipster_registry:
        for src_name, picks in tipsters.items():
            from app.analysis import tipsters as tip_mod
            src_data = tipster_registry
            probs, tip_applied = tip_mod.blend(probs, picks, src_data, src_name)
            if tip_applied:
                mix = {
                    "source": (tip_meta or {}).get("name") or src_name,
                    "rate": (tip_meta or {}).get("rate"),
                    "samples": (tip_meta or {}).get("samples"),
                    "outcome": picks.get("outcome"),
                    "goals": picks.get("goals"),
                    "score": picks.get("score"),
                    "conf": picks.get("conf"),
                }
                break
    probs["tipster_mix"] = mix

    probs["fair_odds"] = {
        "1": round(1 / probs["1x2"]["1"], 2), "x": round(1 / probs["1x2"]["x"], 2),
        "2": round(1 / probs["1x2"]["2"], 2),
        "over_2.5": round(1 / probs["over_under"]["over_2.5"], 2),
        "under_2.5": round(1 / probs["over_under"]["under_2.5"], 2),
        "btts_si": round(1 / probs["btts"]["si"], 2),
        "btts_no": round(1 / probs["btts"]["no"], 2)}

    # ----- il pronostico del modello per ogni mercato (NON più solo valore):
    #      ogni mercato ha un suo pick, basato sulla probabilità più alta.
    probs["model_picks"] = _model_picks(probs, fx)
    probs["featured"] = _featured(probs)

    # ----- giocate consigliate: il pronostico del modello, non "il valore".
    #      Servono probabilità abbastanza alta E quota sana (cap). Niente
    #      giocate a quote assurde solo perché l'edge calcolato "sembra" alto.
    best = []
    for market in ("1x2", "over_under", "btts"):
        mp = (probs["model_picks"] or {}).get(market)
        if not mp:
            continue
        odds, prob = mp.get("odds"), mp.get("prob") or 0
        if not odds:
            continue
        if prob < config.PICK_MIN_PROB:
            continue
        if odds < config.MIN_ODD_TO_BET or odds > config.PICK_MAX_ODD:
            continue
        edge = prob * odds - 1
        if edge < config.VALUE_RELATIVE_EDGE:
            continue
        best.append({"pick": mp["pick"], "odds": odds, "prob": round(prob, 4),
                     "edge": round(edge, 3), "fair": mp.get("fair"),
                     "market": market})
    best.sort(key=lambda b: b["prob"], reverse=True)

    probs["best_bets"] = best[:3]
    probs["calibrated"] = calibrated

    # ri-attacca i dati esterni al dict di predizione (per tracker/store)
    if tipsters:
        probs["tipsters"] = tipsters
    if tip_meta:
        probs["tipster_meta"] = tip_meta

    # motivazione testuale
    probs["motivation"] = _motivation(fx, home_row, away_row, hf, af,
                                      probs, best)
    return probs


def _apply_cal(probs, factors):
    """Corregge le probabilità con i fattori appresi e le rinormalizza."""
    if not factors:
        return None
    if not any(k in factors for k in probs):
        return None
    scaled = {}
    for k, p in probs.items():
        f = factors.get(k, 1.0)
        scaled[k] = clamp(0.02, 0.98, p * f)
    tot = sum(scaled.values())
    if tot <= 0:
        return None
    return {k: round(v / tot, 4) for k, v in scaled.items()}


def clamp(lo, hi, v):
    return max(lo, min(hi, v))


def _best_odds(fx, pick):
    """Migliore quota disponibile per l'esito richiesto, solo dai mercati
    inequivocabili (full time, BTTS). I mercati senza linea (es. 'Match
    goals') vengono esclusi per evitare falsi positivi."""
    pm = pick.lower()
    if pm in ("1", "x", "2"):
        return _max_odds(fx, lambda o:
                         o.market.lower() == "full time" and o.pick.strip().lower() == pm)
    if pm in ("btts si", "btts no"):
        want = "yes" if pm == "btts si" else "no"
        return _max_odds(fx, lambda o:
                         "both teams to score" in o.market.lower() and o.pick.strip().lower() == want)
    if pm in ("over 2.5", "under 2.5"):
        want = "over" if pm == "over 2.5" else "under"
        return _max_odds(fx, lambda o:
                         o.market.lower() in ("over/under 2.5", "over/under")
                         and o.pick.strip().lower().startswith(want))
    return None


def _max_odds(fx, predicate):
    goods = [o.odds for o in fx.odds if predicate(o)]
    return max(goods) if goods else None


# ------------------------------------------------------- mercato / blend
def _market_for(fx, key_map):
    """Probabilità implicite dai mercati (de-juiced) per un mercato."""
    impl = {}
    for o in fx.odds:
        key = key_map(o)
        if key:
            imp = 1.0 / o.odds if o.odds and o.odds > 0 else None
            if imp and (key not in impl or imp > impl[key]):
                impl[key] = imp   # quota migliore -> probabilità implicita minore
    if len(impl) >= 2:
        return markets.dejuice(impl)
    return None


def _market_probs(fx):
    """Probabilità implicite di mercato per 1x2, over/under, btts.

    Le key_map ritornano la CHIAVE canonica (o None): solo così
    ``_market_for`` riece a raccogliere un esito per ogni chiave.
    """
    out = {}
    out["1x2"] = _market_for(fx, lambda o: o.pick.strip().lower()
                             if (o.pick.strip().lower() in ("1", "x", "2")
                                 and o.market.strip().lower() == "full time")
                             else None)
    out["btts"] = _market_for(
        fx, lambda o: ("si" if o.pick.strip().lower() in ("yes", "si")
                       else "no")
        if ("both teams to score" in o.market.strip().lower()
            and o.pick.strip().lower() in ("yes", "no", "si"))
        else None)
    out["over_under"] = _market_for(
        fx, lambda o: ("over_2.5" if o.pick.strip().lower().startswith("over")
                       else "under_2.5")
        if (o.market.strip().lower() in ("over/under 2.5", "over/under")
            and o.pick.strip().lower().startswith(("over", "under")))
        else None)
    return out


def _blend_market(model_p, market_p):
    """Fonde un mercato del modello con quello implicito delle quote."""
    return markets.blend(model_p, market_p, config.MARKET_BLEND_WEIGHT)


# ---------------------------------------------- pronostico del modello
def _conf_label(p):
    if p >= 0.60:
        return "alta"
    if p >= 0.45:
        return "media"
    return "bassa"


def _model_picks(probs, fx):
    """Per ogni mercato, l'esito che il modello ritiene più probabile."""
    out = {}
    for market, mkeys in markets.MARKETS.items():
        pm = probs.get(market) or {}
        if not pm:
            continue
        best_key = max(mkeys, key=lambda k: pm.get(k, 0))
        label = markets.label(market, best_key)
        prob = pm[best_key]
        odds = _best_odds(fx, label)
        out[market] = {
            "pick": label, "key": best_key, "prob": round(prob, 4),
            "odds": odds, "fair": round(1 / prob, 2) if prob > 0 else None,
            "conf": _conf_label(prob),
        }
    return out


def _featured(probs):
    """Pick "headline" del modello: confidenza alta, per la punta del bot."""
    best = None
    for market in ("1x2", "over_under", "btts"):
        mp = (probs.get("model_picks") or {}).get(market)
        if not mp or mp.get("conf") != "alta":
            continue
        if best is None or (mp.get("prob") or 0) > best["prob"]:
            best = {"market": market, **mp}
    return best


def _form_str(fx, side_team, form):
    last5 = (form.get("last_results") or [])[-5:]
    if not last5:
        return None
    w, d, l = 0, 0, 0
    for e in last5:
        r = e.get("result")
        if r == "H":
            w += 1
        elif r == "D":
            d += 1
        elif r == "A":
            l += 1
    return f"{w}V-{l}P-{d}N"


def _motivation(fx, home_row, away_row, hf, af, probs, best):
    parts = []
    hp = (home_row or {}).get("position")
    ap = (away_row or {}).get("position")
    hpts = (home_row or {}).get("points")
    apts = (away_row or {}).get("points")
    title_pos = (f"{fx.home} (#{hp}, {hpts} pt) - {fx.away} (#{ap}, {apts} pt)")
    if hp is not None and ap is not None and apts is not None and hpts is not None:
        gap = hpts - apts
        if abs(gap) >= 6:
            title_pos += f" · {abs(gap)} punti di differenza in classifica"
        if config.OPPONENT_STRENGTH_WEIGHT:
            # forza media avversaria pesata (statistica richiesta: un risultato
            # contro una squadra forte "vale" di più)
            hpp = _points_per_game(home_row)
            app = _points_per_game(away_row)
            title_pos += (f" · forza avv.: {fx.home} {hpp:.2f} pt/g, "
                          f"{fx.away} {app:.2f} pt/g")
    parts.append(title_pos)

    fh = _form_str(fx, fx.home, hf)
    fa = _form_str(fx, fx.away, af)
    if fh and fa:
        parts.append(f"Ultimi 5: {fx.home} {fh}, {fx.away} {fa}.")

    cs_h = hf.get("current_season") or {}
    cs_a = af.get("current_season") or {}
    if cs_h and cs_a:
        parts.append(
            f"In questa stagione {fx.home} segna {round(cs_h['gf'] / max(cs_h['giocate'], 1), 2)} gol"
            f" e ne subisce {round(cs_h['ga'] / max(cs_h['giocate'], 1), 2)} a partita; "
            f"{fx.away} {round(cs_a['gf'] / max(cs_a['giocate'], 1), 2)} fatti,"
            f" {round(cs_a['ga'] / max(cs_a['giocate'], 1), 2)} subiti.")

    sH = hf.get("shots_avg")
    sA = af.get("shots_avg")
    if sH is not None and sA is not None:
        parts.append(f"Tiri in porta: {fx.home} {sH} a gara, {fx.away} {sA} a gara.")

    ref = fx.referee or {}
    if ref.get("name"):
        r = []
        r.append(f"Arbitro: {ref['name']}")
        if ref.get("games"):
            r.append(f"media carriera {ref.get('yellow', 0) / ref['games']:.1f} gialli/"
                     f"{ref.get('red', 0) / ref['games']:.2f} rossi a partita")
        cY_h = hf.get("cards_y_avg")
        cY_a = af.get("cards_y_avg")
        extra = ""
        if cY_h is not None and cY_a is not None:
            extra = f" (squadre: {fx.home} {cY_h}, {fx.away} {cY_a} gialli/gara)"
        parts.append(", ".join(r) + extra + ".")

    h2h = fx.h2h or []
    if h2h:
        wh = sum(1 for m in h2h if m.get("winner") == "H")
        wa = sum(1 for m in h2h if m.get("winner") == "A")
        wd = len(h2h) - wh - wa
        if len(h2h) >= 2:
            parts.append(f"Precedenti recenti ({len(h2h)}): {wh}V {fx.home}, {wd}N, {wa}V {fx.away}.")

    inj_h = [i.get("player") for i in (hf.get("injuries") or [])]
    inj_a = [i.get("player") for i in (af.get("injuries") or [])]
    if inj_h or inj_a:
        def short(lst):
            return ", ".join(lst[:3]) + ("..." if len(lst) > 3 else "")
        msgs = []
        if inj_h:
            msgs.append(f"{fx.home} senza: {short(inj_h)}")
        if inj_a:
            msgs.append(f"{fx.away} senza: {short(inj_a)}")
        parts.append("Attenzione infortuni: " + "; ".join(msgs) + ".")

    ch = fx.coach or {}
    for team_name, side in ((fx.home, "home"), (fx.away, "away")):
        cinf = ch.get(side) or {}
        if not cinf.get("is_new"):
            continue
        mgr = cinf.get("manager") or "un nuovo allenatore"
        d = cinf.get("since_days")
        pd = f" in carica da {d:.0f} giorni" if d is not None else ""
        extra = f" · fonte: {cinf.get('note')}" if cinf.get("note") else ""
        parts.append(f"🔁 {team_name} ha {mgr}{pd}: "
                     f"effetto 'nuova era' attivo{extra}.")

    lambdas = probs.get("lambdas") or {}
    if lambdas:
        parts.append(f"Atteso dal modello: {fx.home} {lambdas['home_goals']:g} — "
                     f"{lambdas['away_goals']:g} {fx.away}.")

    xg = probs.get("xg") or {}
    if xg.get("enabled"):
        xg_note = []
        for team_label, form_side, base_key in (
                (fx.home, hf, "home"), (fx.away, af, "away")):
            gf_avg = None
            seg = (form_side.get("current_season") or {})
            if seg and seg.get("gf") is not None:
                gf_avg = (seg.get("gf") or 0) / max(seg.get("giocate") or 1, 1)
            xg_for = xg.get(f"{base_key}_for")
            xg_ag = xg.get(f"{base_key}_ag")
            bits = []
            if xg_for is not None:
                bits.append(f"xG {xg_for:.2f} a gara")
            if xg_ag is not None:
                bits.append(f"ne concede {xg_ag:.2f}")
            if gf_avg is not None and xg_for and gf_avg - xg_for >= 0.2:
                bits.append("(sopra i numeri: sta segnando più del dovuto)")
            elif gf_avg is not None and xg_for and xg_for - gf_avg >= 0.2:
                bits.append("(sotto i numeri: potrebbe segnare di più)")
            if bits:
                xg_note.append(f"{team_label}: {', '.join(bits)}")
        if xg_note:
            parts.append("Gol attesi: " + "; ".join(xg_note) + ".")

    es = probs.get("exact_score") or []
    if es:
        first = es[0]
        parts.append(
            f"Risultato esatto più probabile: {first['score']} "
            f"({first['prob'] * 100:.0f}%).")

    feat = probs.get("featured")
    if feat:
        parts.append(
            f"Pronostico del modello: {feat['pick'].upper()} "
            f"({feat['prob'] * 100:.0f}%"
            + (f", quota {feat['odds']:.2f}" if feat.get("odds") else "") + ").")
    elif best:
        b0 = best[0]
        label = b0["pick"]
        parts.append(
            f"Pronostico: {label} a {b0['odds']} "
            f"(probabilità modello {b0['prob']*100:.0f}%).")

    mix = probs.get("tipster_mix")
    if mix:
        acc = f"{mix['rate'] * 100:.0f}%" if mix.get("rate") is not None else "n/d"
        parts.append(
            f"Voce esterna ({mix['source']}, affidabilità {acc}): "
            f"1X2 {mix.get('outcome') or '?'}, "
            f"O/U {mix.get('goals') or '?'}, {mix.get('score') or '?'}.")

    if best:
        # nessuna giocata "solo per valore": la quota è sotto il tetto
        parts.append("Giocate consigliate solo se il modello è convinto e la "
                     "quota resta sana (niente quote folli).")

    if probs.get("calibrated"):
        parts.append("Probabilità corrette con quanto imparato dai miei errori "
                     "passati (calibrazione attiva).")

    return " ".join(parts)