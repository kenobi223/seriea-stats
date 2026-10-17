# /pronostici — prossime partite con probabilità e value bet
import time

LABELS = {"1": "1", "x": "x", "2": "2", "over_2.5": "over 2.5",
          "under_2.5": "under 2.5", "si": "btts si", "no": "btts no"}


def _h(s):
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _bar(p):
    p = max(0.0, min(1.0, float(p or 0)))
    full = int(round(p * 10))
    return "█" * full + "░" * (10 - full)


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


def fmt_pronostici(state):
    now = time.time()
    fx_list = [f for f in (state.get("fixtures") or [])
               if f.get("status") != "finished"]
    fx_list.sort(key=lambda f: f.get("start_ts") or 0)
    if not fx_list:
        return "Nessuna partita in calendario al momento."
    lines = ["<b>🎯 Pronostici</b>", ""]
    for fx in fx_list[:8]:
        p = fx.get("predictions") or {}
        probs = p.get("1x2") or {}
        when = (time.strftime("%d/%m %H:%M", time.localtime(fx.get("start_ts") or 0))
                if fx.get("start_ts") else "")
        lines.append(f'🕐 {when}  <b>{_h(fx.get("home"))} - '
                     f'{_h(fx.get("away"))}</b>')
        if probs:
            lines.append(f'   1X2  <b>{probs.get("1", 0) * 100:.0f}%</b> / '
                         f'{probs.get("x", 0) * 100:.0f}% / '
                         f'{probs.get("2", 0) * 100:.0f}%')
        mp = (p.get("model_picks") or {}).get("1x2")
        if mp:
            odds = f' · quota {mp["odds"]:.2f}' if mp.get("odds") else ""
            key = mp.get("key") or mp.get("pick") or "?"
            label = LABELS.get(key, key)
            if str(key).lower() in ("1", "x", "2"):
                label = label.upper()
            lines.append(f'   🎯 <b>{_h(label)}</b> {_bar(mp.get("prob") or 0)} '
                         f'{(mp.get("prob") or 0) * 100:.0f}%{odds}')
        es = p.get("exact_score") or []
        if es:
            lines.append(f'   Risultato esatto: <b>{_h(es[0].get("score"))}</b> '
                         f'{(es[0].get("prob") or 0) * 100:.0f}%')
        best = p.get("best_bets") or []
        if best:
            b = best[0]
            edge = (f' · +{(b.get("edge") or 0) * 100:.0f}%'
                    if b.get("edge") else "")
            lines.append(f'   💰 <b>{_h(b.get("pick"))}</b> @ {b.get("odds")} '
                         f'({(b.get("prob") or 0) * 100:.0f}%){edge}')
        lines.append("")
    return "\n".join(lines).rstrip()


def pronostici(message, u, text, command, args, call, params):
    base = _api_base()
    if not base:
        bot.replyText(u, "Configurazione mancante: variabile API_BASE.")
        return
    try:
        r = requests.get(base + "/api/state", timeout=4)
        data = r.json()
    except Exception:
        bot.replyText(u, "Dati non disponibili, riprova tra qualche minuto.")
        return
    bot.replyText(u, fmt_pronostici(data))
