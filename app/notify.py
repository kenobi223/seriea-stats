"""Notifiche "pronostico indovinato": foto + risultato a chi ha avviato il bot.

Registra le chat che hanno scritto almeno una volta /start (started.json) e,
quando un best-bet del modello viene centrato a fine partita, invia a tutte
queste chat la foto config.WIN_PHOTO con il testo del risultato indovinato.
La notifica parte una sola volta per pronostico (flag win_notified).
"""
import logging
import os
import threading

import requests

import config
from app.analysis import schedina
from app.core import kv

log = logging.getLogger("notify")
_send_lock = threading.Lock()
StartedLock = threading.Lock()

_LBL = {"1": "1 (vittoria casa)", "x": "X (pareggio)", "2": "2 (vittoria ospite)",
        "over_2.5": "Over 2.5", "under_2.5": "Under 2.5",
        "si": "BTTS Sì", "no": "BTTS No"}


def load_started():
    data = kv.read_json("started.json")
    if isinstance(data, list):
        return sorted({c for c in data if isinstance(c, int)})
    return []


def seed_started():
    """Chi già segue squadre ha sicuramente avviato il bot: li aggiunge."""
    started = load_started()
    if started:
        return
    follows = kv.read_json("follows.json")
    if not isinstance(follows, dict):
        return
    froms = sorted({int(c) for c in follows if str(c).lstrip("-").isdigit()})
    if not froms:
        return
    kv.write_json("started.json", froms)
    log.info("started.json creato da follows: %d chat", len(froms))


def register_started(chat_id):
    with StartedLock:
        started = load_started()
        if chat_id in started:
            return
        started.append(chat_id)
        kv.write_json("started.json", started)
        log.info("chat %s registrata agli avvisi pronostici", chat_id)


def _send_photo(chat_id, photo_path, caption):
    if not config.TELEGRAM_BOT_TOKEN or not os.path.exists(photo_path):
        return False
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendPhoto"
    try:
        with _send_lock:
            with open(photo_path, "rb") as f:
                r = requests.post(url,
                                  data={"chat_id": chat_id, "caption": caption},
                                  files={"photo": f}, timeout=25)
        r.raise_for_status()
        return True
    except Exception as e:
        log.warning("foto a %s fallita: %s", chat_id, e)
        return False


def _caption(win):
    lines = ["🎯 PRONOSTICO INDOVINATO!",
             f"⚽ {win['home']} - {win['away']} {win['score']}"
             + (f"  (g. {win['round']})" if win.get("round") else "")]
    for h in win["hits"]:
        prob = ""
        if isinstance(h.get("prob"), (int, float)):
            prob = f" · prob. {h['prob'] * 100:.0f}%"
        odds = f" · quota {h['odds']}" if h.get("odds") else ""
        lines.append(f"✔ {_LBL.get(h['pick'], h['pick'])}{prob}{odds}")
    return "\n".join(lines)


def send_pending_wins(store=None):
    """Foto a tutte le chat avviate, per ogni esito della schedina vinto."""
    if store is None:
        return
    wins = schedina.pending_wins(store)
    if not wins:
        return
    started = load_started()
    if not started:
        seed_started()
        started = load_started()
    if not started:
        return
    if not os.path.exists(config.WIN_PHOTO):
        log.warning("manca %s: notifica pronostici disattivata",
                    config.WIN_PHOTO)
        schedina.mark_wins_notified(store, [w["id"] for w in wins])
        return
    for w in wins:
        caption = _caption(w)
        sent = 0
        for chat in started:
            if _send_photo(chat, config.WIN_PHOTO, caption):
                sent += 1
        schedina.mark_wins_notified(store, [w["id"]])
        log.info("schedina giornata %s: %s %s-%s (%s): foto a %d chat",
                 w.get("round"), w.get("home"), w.get("away"), w.get("score"),
                 w.get("id"), sent)