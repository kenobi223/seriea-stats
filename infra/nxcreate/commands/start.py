# /start — menu principale (comando NxCreate, runtime Python)
def _api_base():
    try:
        v = env.get("API_BASE")
        if v:
            return str(v).rstrip("/")
    except Exception:
        pass
    try:
        import os
        v = os.environ.get("API_BASE")
        if v:
            return str(v).rstrip("/")
    except Exception:
        pass
    return "https://seriea-stats.lucaziello8.workers.dev"


def start(message, u, text, command, args, call, params):
    base = _api_base()
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
