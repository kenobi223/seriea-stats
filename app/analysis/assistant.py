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