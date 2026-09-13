"""Assistente AI: risponde in italiano a domande sul campionato usando
i dati raccolti (tiri in porta, pronostici, errori di quota, arbitri).

Funziona senza API esterne: l'intento viene riconosciuto da parole chiave
e le risposte sono generate dai dati già raccolti.
"""
import logging
import unicodedata

log = logging.getLogger("assistant")


def _norm(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii",
                                                         "ignore").decode().lower()


def _team_sot(form):
    vals = [v for v in (form.get("shots_ontarget") or [])
            if isinstance(v, (int, float))]
    return vals


def _best_sot_pick(team_name, form, side):
    """Trova la soglia più sensata di tiri in porta per la squadra."""
    vals = _team_sot(form)
    if len(vals) < 2:
        return None
    cands = []
    for k in range(3, 9):
        p = sum(1 for v in vals if v > k) / len(vals)
        cands.append((k, round(p, 2)))
    prefer = [c for c in cands if c[1] >= 0.55]
    if prefer:
        k, p = max(prefer, key=lambda c: (c[1] in (0.55, 0.56, 0.57, 0.58, 0.59, 0.60), c[1]))
    else:
        k, p = max(cands, key=lambda c: c[1])
    if p >= 0.80:
        label = "scontato"
    elif p >= 0.58:
        label = "probabile (non scontato)"
    else:
        label = "rischioso"
    avg = round(sum(vals) / len(vals), 1)
    return {"team": team_name, "side": side, "threshold": k,
            "prob": p, "label": label, "avg": avg, "matches": len(vals)}


def sot_recommendations(fixtures):
    recs = []
    for fx in fixtures:
        for side, form, team in (("home", fx.get("form_home"), fx.get("home")),
                                 ("away", fx.get("form_away"), fx.get("away"))):
            pick = _best_sot_pick(team, form, side)
            if pick:
                pick["match"] = f"{fx.get('home')} - {fx.get('away')}"
                pick["start_ts"] = fx.get("start_ts")
                recs.append(pick)
    recs.sort(key=lambda r: r["prob"], reverse=True)
    return recs


# ------------------------------------------------------------- risposte
def _pronostici(fixtures, limit=5):
    bets = []
    for fx in fixtures:
        for b in (fx.get("predictions") or {}).get("best_bets", [])[:2]:
            bets.append({"match": f"{fx.get('home')} - {fx.get('away')}", **b})
    bets.sort(key=lambda b: b.get("edge", 0), reverse=True)
    items = []
    for b in bets[:limit]:
        items.append({
            "title": f"{b['match']} → {b['pick'].upper()} @ {b['odds']}",
            "text": (f"Probabilità modello {b['prob']*100:.0f}% (fair quota {b['fair']}), "
                     f"valore +{b['edge']*100:.0f}%"),
            "tag": "value",
        })
    if not items:
        items.append({"title": "Nessun pronostico", "text": "Nessun valore rilevato.", "tag": "info"})
    return items


def _errori(fixtures, limit=8):
    flags = []
    for fx in fixtures:
        flags += [f for f in fx.get("value_flags", []) if f.get("kind") in ("spread", "arb")]
    items = [{
        "title": f.get("fixture", "") + " · " + str(f.get("pick", "")),
        "text": f.get("message", ""),
        "tag": "alert" if f.get("severity") == "alert" else "warn",
    } for f in flags[:limit]]
    return items


def _arbitri(fixtures):
    rows = []
    for fx in fixtures:
        r = fx.get("referee") or {}
        ypg = r.get("season_y_per_game")
        if ypg is None:
            ypg = (r.get("yellow") or 0) / (r.get("games") or 1)
        rows.append({"match": f"{fx.get('home')} - {fx.get('away')}", "name": r.get("name", "?")})
        rows[-1]["ypg"] = round(ypg, 2)
        rows[-1]["rpg"] = round((r.get("season_r_per_game")
                                 or (r.get("red") or 0) / (r.get("games") or 1)), 2)
    rows.sort(key=lambda x: x["ypg"], reverse=True)
    return [{
        "title": f"{r['match']} · {r['name']}",
        "text": f"Media {r['ypg']} gialli a partita in stagione, {round(r['rpg'], 2)} rossi.",
        "tag": "warn" if r["ypg"] >= 4 else "info",
    } for r in rows]


def _marcatori(fixtures, limit=8):
    picks = []
    for fx in fixtures:
        sc = fx.get("scorer_probabilities") or {}
        for side, team in (("home", fx.get("home")), ("away", fx.get("away"))):
            for p in sc.get(side) or []:
                entry = {"name": p["name"], "team": team,
                         "match": f"{fx.get('home')} - {fx.get('away')}",
                         "prob_pct": p.get("prob_pct", 0),
                         "goals": p.get("goals_last5", 0),
                         "matches": p.get("matches_last5", 0),
                         "avg_sot": p.get("avg_sot", 0),
                         "pos": p.get("position", "?")}
                picks.append(entry)
    picks.sort(key=lambda x: x["prob_pct"], reverse=True)
    return [{
        "title": f"{p['name']} ({p['team']}) · {p['prob_pct']:.1f}%",
        "text": (f"Ruolo {p['pos']} · {p['goals']} gol ultime {p['matches']} gare "
                 f"· media SOT {p['avg_sot']} · partita {p['match']}"),
        "tag": "OK" if p["prob_pct"] >= 40 else ("PROBABILE" if p["prob_pct"] >= 25 else "rischio"),
    } for p in picks[:limit]]


def _tiri_in_porta(fixtures, only="probabili"):
    recs = sot_recommendations(fixtures)
    items = []
    for r in recs:
        tag = {"scontato": "OK", "probabile (non scontato)": "PROBABILE",
               "rischioso": "rischio"}.get(r["label"], "info")
        if only == "probabili" and r["label"] not in ("probabile (non scontato)", "scontato"):
            continue
        items.append({
            "title": f"{r['team']} · over {r['threshold']} tiri in porta ({r['match']})",
            "text": (f"Probabilità {r['prob']*100:.0f}% · media {r['avg']} tiri/gara "
                     f"nelle ultime {r['matches']} gare · {r['label']}"),
            "tag": tag,
        })
    return items


def _xg_compare(fixtures, limit=10):
    items = []
    for fx in fixtures:
        p = fx.get("predictions") or {}
        x = p.get("xg") or {}
        if not x.get("enabled"):
            continue
        items.append({
            "title": f"{fx.get('home')} - {fx.get('away')}",
            "text": (f"xG: {fx.get('home')} {x['home_for']:.2f} prodotti / "
                     f"{x['home_ag']:.2f} concessi · {fx.get('away')} "
                     f"{x['away_for']:.2f} prodotti / {x['away_ag']:.2f} concessi "
                     f"(campione {x.get('played_home')}/{x.get('played_away')} partite)"),
            "tag": "info",
        })
    return items


def _partita(fixture):
    p = fixture.get("predictions") or {}
    lines = []
    lines.append(f"{fixture.get('home')} - {fixture.get('away')} (giornata {fixture.get('round') or '?'})")
    if "1x2" in p:
        lines.append("Probabilità 1X2: " + " · ".join(
            f"{k} {v*100:.0f}%" for k, v in sorted(p["1x2"].items())))
    for b in p.get("best_bets", [])[:2]:
        lines.append(f"Punta: {b['pick']} @ {b['odds']} (valore +{b['edge']*100:.0f}%)")
    for sp in fixture.get("value_flags", []):
        lines.append("⚠ " + sp.get("message", ""))
    if p.get("motivation"):
        lines.append("Perché: " + p["motivation"])
    return lines


def answer(raw_question, fixtures):
    """Chiede all'assistente e restituisce una risposta strutturata."""
    q = _norm(raw_question)
    items = []

    if any(k in q for k in ("tiri in porta", "tiro in porta", "scontat", "probab")):
        only = "probabili" if not ("scontat" in q and "non scontat" not in q) else "tutti"
        if "non scontat" in q:
            only = "probabili"
        elif "scontat" in q and "non" not in q:
            only = "tutti"
        else:
            only = "probabili"
        items = _tiri_in_porta(fixtures, only=only)
        intro = ("Tiri in porta per la prossima giornata. I \"scontati\" hanno probabilità "
                 "≥80% nelle ultime gare; i \"probabili\" 55-80%: meno certezza, ma di solito "
                 "quota migliore.")
        intent = "tiri_in_porta"

    elif any(k in q for k in ("errore", "arbitrag", "disalline", "quota", "bookmaker")):
        items = _errori(fixtures)
        intro = "Errori di quota (disallineamenti tra bookmaker) rilevati nell'ultimo refresh:"
        intent = "errori"

    elif any(k in q for k in ("arbitr", "cartellin", "rosso", "giallo")):
        items = _arbitri(fixtures)
        intro = "Arbitri delle prossime partite ordinati per media cartellini in stagione:"
        intent = "arbitri"

    elif any(k in q for k in ("pronostic", "consigli", "suggerisci", "miglior",
                              "punta", "value", "scelta", "giornata")):
        items = _pronostici(fixtures)
        intro = "I pronostici con valore migliore secondo il modello:"
        intent = "pronostici"

    elif any(k in q for k in ("xg", "gol attesi", "expected", "attesi")):
        items = _xg_compare(fixtures)
        intro = ("Gol attesi (xG) per le prossime partite: cosa producono e subiscono "
                 "le squadre dagli expected goals delle partite in stagione:")
        intent = "xg"

    elif any(k in q for k in ("marcator", "goleador", "chi segna",
                              "probabilità gol", "andare a segno", "a segno")):
        items = _marcatori(fixtures)
        intro = ("Probabilità di andare a segno valutate su forma ultime 5 "
                 "partite, difesa avversaria e tiri in porta: i migliori "
                 "marcatori della giornata:")
        intent = "marcatori"

    else:
        target = None
        for fx in fixtures:
            if _norm(fx.get("home")) in q or _norm(fx.get("away")) in q or \
                    all(t in q for t in (_norm(fx.get("home")), _norm(fx.get("away")))):
                target = fx
                break
        if target:
            return {
                "intent": "partita",
                "intro": f"Ecco l'analisi di {target.get('home')} - {target.get('away')}:",
                "lines": _partita(target),
                "items": [],
            }
        items = _pronostici(fixtures) + _errori(fixtures, 3)
        intro = ("Prova a chiedermi qualcosa come: \"che tiri in porta mi consigli?\", "
                 "\"ci sono errori di quota?\", \"pronostici della giornata\" o "
                 "nomina due squadre (es. \"analizza Juventus - Milan\"). Intanto: ")
        intent = "overview"

    return {
        "intent": intent,
        "intro": intro,
        "lines": [],
        "items": items,
    }