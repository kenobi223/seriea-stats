# /classifica — classifica Serie A dalla stessa API del sito


def _h(s):
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def fmt_classifica(state):
    standings = state.get("standings") or []
    if not standings:
        return "Nessun dato classifica."
    rows = sorted(standings, key=lambda x: (x.get("position") or 99))[:20]
    lines = ["<b>🏆 Classifica Serie A</b>", "", "<pre>"]
    for r in rows:
        pos = r.get("position") or 0
        name = _h(str(r.get("name") or ""))[:16]
        lines.append(f"{pos:>2}. {name:<16} {int(r.get('points') or 0):>3}pt  "
                     f"{int(r.get('played') or 0):>2}g  "
                     f"{int(r.get('gf') or 0):>3}-{int(r.get('ga') or 0):<3}")
    lines.append("</pre>")
    return "\n".join(lines)


def classifica(message, u, text, command, args, call, params):
    base = (env.get("API_BASE") or "").rstrip("/")
    if not base:
        bot.replyText(u, "Configurazione mancante: variabile API_BASE.")
        return
    try:
        r = requests.get(base + "/api/state", timeout=4)
        data = r.json()
    except Exception:
        bot.replyText(u, "Dati non disponibili, riprova tra qualche minuto.")
        return
    bot.replyText(u, fmt_classifica(data))
