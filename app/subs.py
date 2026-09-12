"""Abbonamenti "completo" con Telegram Stars (50 ⭐/settimana, 100 ⭐/mese).

Quota gratuita: 1 pronostico al giorno per chat. Il proprietario ("il capo",
config.TELEGRAM_OWNER_IDS) ha tutto gratis. I dati restano in kv (Redis/disco)
così sopravvivono anche al filesystem effimero di Render.
"""
import logging
import time

import config
from app.core import kv

log = logging.getLogger("subs")

WEEK_SECONDS = 7 * 24 * 3600
MONTH_SECONDS = 30 * 24 * 3600
TRIAL_SECONDS = 24 * 3600

# Voucher -> abbonamento "a vita" (scadenza 1° gennaio 2100).
LIFETIME_TS = 4102444800

# "week" -> (stelle, durata in secondi)
PLANS = {
    "week": (config.SUBS_WEEK_STARS, WEEK_SECONDS),
    "month": (config.SUBS_MONTH_STARS, MONTH_SECONDS),
}


def redeem_coupon(chat_id, code):
    """Applica un voucher: True se valido (completo A VITA)."""
    code = (code or "").strip().lower()
    valid = [c.lower() for c in config.SUBS_COUPONS] + _extra_coupons()
    if code not in valid or not code:
        return False
    _grant_lifetime(chat_id)
    log.info("subs: voucher %r riscattato da chat %s (a vita)", code, chat_id)
    return True


def _extra_coupons():
    d = _load()
    extra = d.get("_coupons") or []
    return [c.lower() for c in extra if isinstance(c, str)]


def add_coupon(code):
    """Aggiunge un voucher valido (usato dal comando /capo)."""
    code = (code or "").strip()
    if not code:
        return False
    d = _load()
    extra = d.setdefault("_coupons", [])
    if code.lower() in [c.lower() for c in extra]:
        return False
    extra.append(code)
    _save(d)
    log.info("subs: coupon %r aggiunto dal Capo", code)
    return True


def _grant_lifetime(chat_id):
    d = _load()
    d[str(chat_id)] = LIFETIME_TS
    _save(d)


def grant_lifetime(chat_id):
    """Abbonamento a vita per una chat (usato dal comando /capo)."""
    _grant_lifetime(chat_id)
    log.info("subs: chat %s ha ricevuto il completo a vita dal Capo", chat_id)
    return True


def _load():
    d = kv.read_json("subs.json")
    return d if isinstance(d, dict) else {}


def _save(d):
    kv.write_json("subs.json", d)


def is_owner(chat_id):
    return chat_id in config.TELEGRAM_OWNER_IDS


def expiry(chat_id):
    """Timestamp di scadenza (0 = mai abbonato)."""
    return int(_load().get(str(chat_id)) or 0)


def is_pro(chat_id):
    """True se ha il completo: proprietario sempre, altrimenti scadenza futura."""
    if is_owner(chat_id):
        return True
    return expiry(chat_id) > time.time()


def is_lifetime(chat_id):
    return expiry(chat_id) >= LIFETIME_TS


def start_trial(chat_id):
    """Prova gratuita di 24 ore dal momento del click (una sola volta a chat)."""
    if is_owner(chat_id) or is_pro(chat_id):
        return False
    if trial_used(chat_id):
        return False
    d = _load()
    d[str(chat_id)] = int(time.time()) + TRIAL_SECONDS
    d.setdefault("_trial_used", {})[str(chat_id)] = int(time.time())
    _save(d)
    log.info("subs: chat %s ha attivato la prova gratuita 24h", chat_id)
    return True


def trial_used(chat_id):
    d = _load()
    return bool((d.get("_trial_used") or {}).get(str(chat_id)))


def subscribe(chat_id, plan):
    """Estende l'abbonamento dalla scadenza attuale (o da ora) di plan giorni."""
    if plan not in PLANS:
        plan = "month"
    days = PLANS[plan][1]
    base = max(expiry(chat_id), int(time.time()))
    until = base + days
    d = _load()
    d[str(chat_id)] = until
    _save(d)
    log.info("subs: chat %s abbonata (%s) fino a %s", chat_id, plan, until)
    return until


def _today():
    return time.strftime("%Y-%m-%d")


def free_used(chat_id):
    """Quanti pronostici gratuiti già usati oggi."""
    d = _load()
    days = d.get("_daily") or {}
    return int((days.get(_today()) or {}).get(str(chat_id), 0))


def note_free_used(chat_id):
    """Registra l'uso di un pronostico gratuito oggi."""
    d = _load()
    days = d.setdefault("_daily", {})
    day = days.setdefault(_today(), {})
    day[str(chat_id)] = day.get(str(chat_id), 0) + 1
    _save(d)