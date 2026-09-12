"""Alert Telegram "pronto per l'Over 2.5".

Media mobile degli ultimi N pronostici O/U 2.5 valutati (l'esito over/under
suggerito dal modello). Quando la percentuale di centratura della finestra
supera ``config.OU_ALERT_TARGET`` (85%) si invia una notifica al proprietario
(@ziosapi) con la percentuale raggiunta, la finestra usata e un promemoria
che è il momento di giocare.

L'alert parte una sola volta finché la media non scende sotto la soglia e
poi la risale (flag ``alerted`` per il livello corrente).
"""
import logging
import threading
import time

import config
from app.analysis import tracker
from app.core import kv
from app.live import telegram_send

log = logging.getLogger("ou_alert")

_send_lock = threading.Lock()
_BOSS = "1694501243"   # @ziosapi, il proprietario (default TELEGRAM_OWNER_IDS[0])

_LBL_PICK = {"over_2.5": "Over 2.5", "under_2.5": "Under 2.5"}


def _alert_state():
    """Stato persistente a livello (chiave voto -> già avvisato?)."""
    data = kv.read_json("ou_alert.json")
    if isinstance(data, dict):
        return {
            "level": data.get("level"),
            "last_sent": data.get("last_sent"),
        }
    return {"level": None, "last_sent": None}


def _save_state(level, ts):
    kv.write_json("ou_alert.json", {"level": level, "last_sent": ts})


def over_under_window():
    """Ultimi ``OU_ALERT_WINDOW`` pronostici O/U valutati: esito suggerito dal
    modello (quello con probabilità più alta) e se è stato indovinato.

    Rientrano i record che:
      - sono stati valutati (hanno il risultato reale)
      - hanno probabilità O/U salvate
    L'esito "suggerito" è quello che il modello riteneva più probabile.
    """
    data = tracker.load()
    records = [r for r in data.get("records", [])
               if r.get("evaluated") and r.get("result")]

    rows = []
    for r in records:
        probs = (r.get("probs") or {}).get("over_under") or {}
        if not probs:
            continue
        pick = max(probs, key=probs.get)
        real = (r.get("result") or {}).get("over_under")
        if not real:
            continue
        rows.append({
            "home": r.get("home"), "away": r.get("away"),
            "round": r.get("round"),
            "score": f"{r['result']['home_score']}-{r['result']['away_score']}",
            "pick": pick, "prob": probs.get(pick),
            "hit": 1 if pick == real else 0,
        })

    # ordina per partita (per start non salvato nel record, uso risultato/round:
    # manteniamo l'ordine di registrazione) e prendi gli ultimi N
    rows = rows[-config.OU_ALERT_WINDOW:]
    return rows


def check_and_alert():
    """Controlla la media mobile O/U e, se >= soglia, invia l'alert @ziosapi."""
    if not config.TELEGRAM_BOT_TOKEN:
        return

    rows = over_under_window()
    if len(rows) < config.OU_ALERT_WINDOW:
        return

    ok = sum(r["hit"] for r in rows)
    total = len(rows)
    rate = ok / total

    state = _alert_state()
    level_bucket = round(rate * 100)

    if rate < config.OU_ALERT_TARGET:
        # sotto soglia: azzera per ri-armare l'alert quando risale
        if state["level"] is not None:
            _save_state(None, time.time())
        return

    # sopra soglia: avvisa solo se non l'abbiamo già fatto per questo livello
    if state["level"] == level_bucket:
        return

    lines = [
        "🎯 TARGET 85% RAGGIUNTO — OVER/UNDER 2.5",
        f"✔ Centrati {ok} su {total} degli ultimi {total} pronostici "
        f"O/U 2.5 suggeriti ({rate * 100:.0f}%).",
        "💰 È il momento di giocare gli Over/Under 2.5!",
        "",
        "Ultimi risultati:",
    ]
    for r in reversed(rows):
        mark = "✔" if r["hit"] else "✘"
        prob = f" ({r['prob'] * 100:.0f}%)" if isinstance(r.get("prob"), (int, float)) else ""
        lines.append(
            f"{mark} {r['home']} {r['score']} {r['away']} "
            f"→ {_LBL_PICK.get(r['pick'], r['pick'])}{prob}")
    text = "\n".join(lines)

    with _send_lock:
        telegram_send(_BOSS, text)
        _save_state(level_bucket, time.time())
    log.info("ou_alert: target %.0f%% raggiunto (%s/%s), notifica a %s",
             rate * 100, ok, total, _BOSS)
