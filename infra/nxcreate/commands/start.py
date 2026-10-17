# /start — menu principale (comando NxCreate, runtime Python)
def start(message, u, text, command, args, call, params):
    base = (env.get("API_BASE") or "").rstrip("/")
    lines = [
        "<b>Serie A Stats</b> ⚽",
        "",
        "Comandi:",
        "/schedina — esiti della giornata",
        "/pronostici — probabilità e value bet",
        "/classifica — classifica Serie A",
        "/risultati — ultime giornate",
        "/aiuto — questo menu",
    ]
    if base:
        lines += ["", f'Sito: <a href="{base}">{base.replace("https://", "")}</a>']
    User.saveData("started", True)
    bot.replyText(u, "\n".join(lines))
