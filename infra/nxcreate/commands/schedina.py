# /schedina — esiti della schedina della giornata (stessa API del sito)
LABELS = {"1": "1", "x": "x", "2": "2", "over_2.5": "over 2.5",
          "under_2.5": "under 2.5", "si": "btts si", "no": "btts no"}


def _h(s):
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def fmt_schedina(slip):
    picks = slip.get("picks") or []
    if not picks:
        return ("Nessuna schedina ancora pronta: la creo prima della "
                "prima partita della giornata.")
    lines = [f'<b>🎫 Schedina giornata {slip.get("round") or "?"}</b>', ""]
    for p in picks:
        pick = LABELS.get(p.get("pick") or "?", p.get("pick") or "?")
        odds = p.get("odds") or 0
        pct = (p.get("prob") or 0) * 100
        score = p.get("score") or ""
        lines.append(f'<b>{_h(p.get("home"))} - {_h(p.get("away"))}</b>')
        if p.get("result") == "win":
            lines.append(f"   ✔ {pick} @ {odds}  [{pct:.0f}%]  {score} ✅")
        elif p.get("result") == "loss":
            lines.append(f"   ✘ {pick} @ {odds}  [{pct:.0f}%]  {score} ❌")
        else:
            lines.append(f"   ◻ {pick} @ {odds}  [{pct:.0f}%]  ⏳")
    wins = sum(1 for p in picks if p.get("result") == "win")
    losses = sum(1 for p in picks if p.get("result") == "loss")
    lines.append("")
    lines.append(f"<b>Combinata: {wins} vinti · {losses} persi</b>")
    hist = slip.get("history") or []
    if hist:
        lines.append("")
        lines.append("<b>📚 Schedine passate:</b>")
        for h in reversed(hist):
            lines.append(f'Giornata {h.get("round")}: {h.get("wins", 0)} '
                         f'vinti · {h.get("losses", 0)} persi')
    return "\n".join(lines)


def schedina(message, u, text, command, args, call, params):
    base = (env.get("API_BASE") or "").rstrip("/")
    if not base:
        bot.replyText(u, "Configurazione mancante: variabile API_BASE.")
        return
    try:
        r = requests.get(base + "/api/schedina", timeout=4)
        data = r.json()
    except Exception:
        bot.replyText(u, "Dati non disponibili, riprova tra qualche minuto.")
        return
    bot.replyText(u, fmt_schedina(data))
