"""Assistente AI: risponde in italiano a domande sul campionato usando
i dati raccolti (pronostici, errori di quota).

Funziona senza API esterne: l'intento viene riconosciuto da parole chiave
e le risposte sono generate dai dati già raccolti.
"""
import logging
import unicodedata

log = logging.getLogger("assistant")


def _norm(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii",
                                                         "ignore").decode().lower()


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


def _partita(fixture):
    p = fixture.get("predictions") or {}
    home, away = fixture.get("home"), fixture.get("away")
    lines = []
    # bar style: intro calda
    lines.append(f"Ah, {home} - {away} di giornata {fixture.get('round') or '?'}... bella partita, te lo dico io come la vedo.")
    if "1x2" in p:
        prob = p["1x2"]
        # frase bar invece di lista tecnica
        top = max(prob, key=lambda k: prob[k])
        top_pct = prob[top]*100
        label = {"1": home, "x": "pareggio", "2": away}[top]
        lines.append(f"Secondo me qui {label} è favorito al {top_pct:.0f}% (1: {prob.get('1',0)*100:.0f}% · X: {prob.get('x',0)*100:.0f}% · 2: {prob.get('2',0)*100:.0f}%).")
        if p.get("lambdas"):
            lh, la = p["lambdas"].get("home_goals"), p["lambdas"].get("away_goals")
            if lh is not None and la is not None:
                lines.append(f"Mi aspetto più o meno {lh:.2f} gol per {home} e {la:.2f} per {away}... partita che si sblocca, non 0-0 da sbadiglio.")
        if p.get("exact_score"):
            es = p["exact_score"][0]
            lines.append(f"Se devo sparare un risultato, ti dico {es['score']} al {es['prob']*100:.0f}%... da bar, eh, prendilo con le pinze.")
    for b in p.get("best_bets", [])[:1]:
        lines.append(f"E se proprio vuoi puntarci due spicci, il modello mi dice '{b['pick']}' a {b['odds']} (prob {b['prob']*100:.0f}%)... ma gioca leggero, che il pallone è strano.")
    if p.get("motivation"):
        # rendi la motivazione tecnica più bar-style: spezza e aggiungi intercalare
        mot = p["motivation"]
        # prendi solo prime 2 frasi per non annoiare
        parts = mot.split(". ")
        short = ". ".join(parts[:2])
        if short and not short.endswith("."):
            short += "."
        lines.append(f"Ti spiego perché: {short} Insomma, al bar diremmo che chi sta meglio ora ha quel pizzico in più.")
    else:
        lines.append("Non ho ancora abbastanza dati per darti il perché preciso... ripassa più vicino al fischio.")
    return lines


def answer(raw_question, fixtures):
    """Chiede all'assistente e restituisce una risposta strutturata."""
    q = _norm(raw_question)
    items = []

    # PRIORITA' 1: se la domanda nomina una partita specifica, spiega SEMPRE quella
    # (anche se contiene parole come "pronostico" -> altrimenti finiva nel ramo generico)
    target = None
    for fx in fixtures:
        hn = _norm(fx.get("home"))
        an = _norm(fx.get("away"))
        if hn and hn in q or an and an in q:
            target = fx
            break
        # match con entrambi i nomi (es. "juventus - milan")
        if hn and an and hn in q and an in q:
            target = fx
            break
    if target and any(k in q for k in ("spiega", "perche", "motivo", "analizza", "pronostic", "quote", "probabilita", "gol attesi", "xg")):
        return {
            "intent": "partita",
            "intro": f"Oh, {target.get('home')} - {target.get('away')}? Siediti, te la racconto come al bar:",
            "lines": _partita(target),
            "items": [],
        }

    if any(k in q for k in ("errore", "arbitrag", "disalline", "quota", "bookmaker")):
        items = _errori(fixtures)
        intro = "Errori di quota (disallineamenti tra bookmaker) rilevati nell'ultimo refresh:"
        intent = "errori"

    elif any(k in q for k in ("pronostic", "consigli", "suggerisci", "miglior",
                              "punta", "value", "scelta", "giornata")):
        items = _pronostici(fixtures)
        intro = "I pronostici con valore migliore secondo il modello:"
        intent = "pronostici"

    else:
        if target:
            return {
                "intent": "partita",
                "intro": f"Ah, {target.get('home')} - {target.get('away')}? Te la leggo come la vedo io al bar:",
                "lines": _partita(target),
                "items": [],
            }
        items = _pronostici(fixtures) + _errori(fixtures, 3)
        intro = ("Prova a chiedermi qualcosa come: \"pronostici della giornata\", "
                 "\"ci sono errori di quota?\" o "
                 "nomina due squadre (es. \"analizza Juventus - Milan\"). Intanto: ")
        intent = "overview"

    return {
        "intent": intent,
        "intro": intro,
        "lines": [],
        "items": items,
    }