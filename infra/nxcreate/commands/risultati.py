# /risultati — risultati delle ultime giornate dalla stessa API del sito


def _h(s):
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def fmt_risultati(state):
    results = state.get("results") or []
    if not results:
        return "Nessun risultato disponibile."
    lines = ["<b>📋 Risultati Serie A</b>", ""]
    for rnd in results[-4:]:
        lines.append(f'<b>Giornata {rnd.get("round")}</b>')
        for m in rnd.get("matches") or []:
            lines.append(f'  <b>{_h(m.get("home"))} {_h(m.get("score"))} '
                         f'{_h(m.get("away"))}</b>')
        lines.append("")
    return "\n".join(lines).rstrip()


def risultati(message, u, text, command, args, call, params):
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
    bot.replyText(u, fmt_risultati(data))
