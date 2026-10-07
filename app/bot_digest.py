"""Digest automatici Telegram: presagi del giorno, riepilogo giornata del
mattino e promemoria/recap per le squadre seguite.

- Testi in HTML (parse_mode="HTML"), valori dinamici escapati con _h().
- Invio solo se TELEGRAM_BOT_TOKEN è presente (mai in locale senza token).
- Dedup tramite data/digest_sent.json (kv: Redis su Render, disco in locale).
- Orari/finestre calcolati su Europe/Rome con fallback al fuso dell'host.
"""
import datetime as dt
import logging
import time

import requests

import config
from app.core import kv
from app.i18n import _tr

log = logging.getLogger("bot_digest")

MAX_ROWS = 7
_MIN_P = 0.60          # soglia "sicura" per i pick del modello senza best_bet
_MESES = ("gen", "feb", "mar", "apr", "mag", "giu",
          "lug", "ago", "set", "ott", "nov", "dic")
_GIORNI = ("lun", "mar", "mer", "gio", "ven", "sab", "dom")

try:                                    # Python 3.9+, dati tz su Linux/Render
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Europe/Rome")
except Exception:                       # Windows senza tzdata: fuso host
    _TZ = None


def _h(s):
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _dt(ts=None):
    t = time.time() if ts is None else ts
    if _TZ is not None:
        return dt.datetime.fromtimestamp(t, _TZ)
    return dt.datetime.fromtimestamp(t)


def _hm(ts):
    return _dt(ts).strftime("%H:%M")


def _when(ts):
    d = _dt(ts)
    return f"{_GIORNI[d.weekday()]} {d.day:02d}/{_MESES[d.month - 1]} · {d.strftime('%H:%M')}"


def _rel_day(ts):
    today = _dt().date()
    day = _dt(ts).date()
    diff = (day - today).days
    if diff == 0:
        return "oggi"
    if diff == 1:
        return "domani"
    return _when(ts).split(" · ")[0]


def _bar(p):
    p = max(0.0, min(1.0, float(p or 0)))
    n = 10
    full = int(round(p * n))
    return "█" * full + "░" * (n - full)


def _kb(rows):
    def btn(t, d):
        if d.startswith("http"):
            return {"text": t, "url": d}
        return {"text": t, "callback_data": d}
    return {"inline_keyboard": [[btn(t, d) for t, d in row] for row in rows]}


def _send(chat_id, text, reply_markup=None):
    if not config.TELEGRAM_BOT_TOKEN:
        return False
    url = ("https://api.telegram.org/bot"
           f"{config.TELEGRAM_BOT_TOKEN}/sendMessage")
    payload = {"chat_id": chat_id, "text": text,
               "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(url, json=payload, timeout=20)
        data = r.json()
        if data.get("ok"):
            return True
        desc = str(data.get("description") or "")
        if "parse" in desc:             # fallback: ritenta senza HTML
            payload.pop("parse_mode", None)
            data = requests.post(url, json=payload, timeout=20).json()
            if data.get("ok"):
                return True
            desc = str(data.get("description") or "")
        log.warning("digest a %s fallito: %s", chat_id, desc)
    except Exception as e:
        log.warning("digest a %s fallito: %s", chat_id, e)
    return False


# ------------------------------------------------------------------- testi
def _upcoming(store, within_days=14):
    now = time.time()
    out = []
    for f in store.get("fixtures") or []:
        ts = f.get("start_ts") or 0
        if f.get("status") == "finished" or not ts:
            continue
        if ts >= now - 3 * 3600 and ts <= now + within_days * 86400:
            out.append(f)
    return sorted(out, key=lambda f: f.get("start_ts") or 0)


def _pick_of(fx):
    """Riga di pronostico migliore per una partita (HTML)."""
    from app.core import markets as mk
    preds = fx.get("predictions") or {}
    best = (preds.get("best_bets") or [{}])[0]
    if best.get("pick"):
        market = best.get("market") or "1x2"
        label = mk.label(market, best["pick"])
        if market == "1x2":
            label = label.upper()
        prob = best.get("prob") or 0
        odds = best.get("odds")
        fair = best.get("fair")
        edge = best.get("edge")
        if edge is None and odds and fair:
            edge = (odds / fair) - 1        # valore intrinseco quota vs fair
    else:
        mp = (preds.get("model_picks") or {}).get("1x2") or {}
        if not mp.get("pick"):
            return None
        key = mp.get("key") or mp["pick"]
        label = mk.label("1x2", key).upper() \
            if str(key).lower() in ("1", "x", "2") else mk.label("1x2", key)
        prob = mp.get("prob") or 0
        odds = mp.get("odds")
        fair = mp.get("fair")
        edge = None
        if odds and fair:
            edge = (odds / fair) - 1
    line = (f"   🎯 <b>{_h(label)}</b> {_bar(prob)} {prob * 100:.0f}%"
            f"  · quota {odds if odds else 'n/d'}"
            + (f"  · fair {fair:.2f}" if fair else "")
            + (f"  · <b>+{edge * 100:.0f}%</b>" if edge else ""))
    return line


def presagi_text(store):
    """I presagi del giorno: top pick per probabilità (value + sicuri)."""
    now = time.time()
    rows = []
    for fx in _upcoming(store):
        if (fx.get("start_ts") or 0) <= now:
            continue
        preds = fx.get("predictions") or {}
        cands = []
        for b in preds.get("best_bets") or []:
            if b.get("pick") and b.get("prob"):
                cands.append(b)
        if not cands:
            for key in ("1x2", "over_under", "btts"):
                mp = (preds.get("model_picks") or {}).get(key) or {}
                if mp.get("pick") and (mp.get("prob") or 0) >= _MIN_P:
                    cands.append(mp)
                    break
        if cands:
            top = max(cands, key=lambda b: b.get("prob") or 0)
            rows.append((top.get("prob") or 0, fx))
    rows.sort(key=lambda r: -r[0])
    lines = [_tr("it", "presagi_title")]
    if not rows:
        lines.append(_tr("it", "presagi_empty"))
        return "\n".join(lines)
    for prob, fx in rows[:MAX_ROWS]:
        when = _when(fx.get("start_ts") or 0)
        lines.append(f"🎯 <b>{_h(fx.get('home'))} - {_h(fx.get('away'))}</b>"
                     f"  ·  {when}")
        row = _pick_of(fx)
        if row:
            lines.append(row)
        lines.append("")
    tracking = store.get("tracking") or {}
    if tracking.get("bets_total"):
        lines.append(_tr("it", "pronostici_note",
                         hit=tracking.get("bets_hit"),
                         tot=tracking["bets_total"],
                         rate=tracking["bets_rate"] * 100))
    lines.append("")
    lines.append(_tr("it", "disclaimer"))
    return "\n".join(lines)


def digest_text(store):
    """Riepilogo della giornata di oggi: partite rimaste + pronostico."""
    now = time.time()
    todays = [f for f in _upcoming(store, within_days=1)
              if _dt(f.get("start_ts")).date() == _dt().date()
              and (f.get("start_ts") or 0) > now]
    if not todays:
        return None
    rnd = todays[0].get("round")
    lines = [_tr("it", "digest_title", r=rnd), "",
             _tr("it", "digest_sub"), ""]
    for fx in todays[:10]:
        lines.append(f"🕐 <b>{_hm(fx.get('start_ts'))}</b>  "
                     f"<b>{_h(fx.get('home'))} - {_h(fx.get('away'))}</b>")
        row = _pick_of(fx)
        if row:
            lines.append(row)
        lines.append("")
    lines.append(_tr("it", "disclaimer"))
    return "\n".join(lines)


def recap_text(store, teams):
    """Promemoria delle squadre seguite con fixture, forma e morale."""
    fixtures = _upcoming(store, within_days=4)
    tomorrow = _dt().date() + dt.timedelta(days=1)
    lines = [_tr("it", "recap_title"), ""]
    found = False
    for team in teams:
        for fx in fixtures:
            is_home = fx.get("home") == team
            is_away = fx.get("away") == team
            if not (is_home or is_away):
                continue
            day = _dt(fx.get("start_ts")).date()
            if day not in (_dt().date(), tomorrow):
                continue
            opp = fx.get("away") if is_home else fx.get("home")
            form = (fx.get("form_home") if is_home else fx.get("form_away")) or {}
            mor = ((fx.get("morale") or {}).get("home" if is_home else "away")) or {}
            where = "casa" if is_home else "trasferta"
            lines.append(
                f"⚽ <b>{_h(team)}</b> — {_rel_day(fx.get('start_ts'))} "
                f"{_hm(fx.get('start_ts'))} in {where} con "
                f"<b>{_h(opp)}</b>")
            bits = []
            chars = form.get("form_chars")
            if chars:
                bits.append(f"📋 forma <code>{_h(chars)}</code>")
            if mor.get("label"):
                bits.append(f"🎭 morale {mor.get('label')} "
                            f"{mor.get('score')}/10")
            if bits:
                lines.append("   " + "  ·  ".join(bits))
            lines.append("")
            found = True
            break
    if not found:
        return None
    lines.append(_tr("it", "disclaimer"))
    return "\n".join(lines)


# ------------------------------------------------------------------ invii
def _sent_map():
    data = kv.read_json("digest_sent.json")
    return data if isinstance(data, dict) else {}


def _mark(key, sent_map):
    sent_map[key] = int(time.time())
    kv.write_json("digest_sent.json", sent_map)


def send_digest(store):
    """Mattino della giornata (08:00 → ultimo fischio): riepilogo a /start."""
    if not config.TELEGRAM_BOT_TOKEN:
        return 0
    now = time.time()
    dnow = _dt()
    if dnow.hour < 8:
        return 0
    todays = [f for f in _upcoming(store, within_days=1)
              if _dt(f.get("start_ts")).date() == dnow.date()
              and (f.get("start_ts") or 0) > now]
    if not todays:
        return 0
    if now >= max(f.get("start_ts") or 0 for f in todays):
        return 0
    key = f"digest-{dnow.date().isoformat()}"
    sent = _sent_map()
    if key in sent:
        return 0
    text = digest_text(store)
    if not text:
        return 0
    from app import notify
    notify.seed_started()
    chats = notify.load_started()
    if not chats:
        return 0
    kb = _kb([[("🏠 Menu", "m")]])
    n = 0
    for chat in chats:
        if _send(chat, text, kb):
            n += 1
    if n:
        _mark(key, sent)
        log.info("digest giornata inviato a %d/%d chat", n, len(chats))
    return n


def send_recaps(store):
    """Sera prima della partita (18:00→23:59): promemoria squadre seguite."""
    if not config.TELEGRAM_BOT_TOKEN:
        return 0
    now = time.time()
    dnow = _dt()
    if dnow.hour < 18:
        return 0
    follows = kv.read_json("follows.json")
    if not isinstance(follows, dict) or not follows:
        return 0
    tomorrow = (dnow.date() + dt.timedelta(days=1)).isoformat()
    sent = _sent_map()
    kb = _kb([[("🏠 Menu", "m")]])
    n = 0
    touched = False
    for chat, teams in follows.items():
        if not teams or not str(chat).lstrip("-").isdigit():
            continue
        key = f"recap-{tomorrow}-{chat}"
        if key in sent:
            continue
        text = recap_text(store, teams)
        if not text:
            continue
        if _send(int(chat), text, kb):
            _mark(key, sent)
            touched = True
            n += 1
    if touched:
        log.info("recap squadre inviato a %d chat", n)
    return n


def send_all(store):
    """Punto d'ingresso per lo scheduler: entrambi i digest, best effort."""
    total = 0
    try:
        total += send_digest(store)
    except Exception as e:
        log.debug("send_digest fallito: %s", e)
    try:
        total += send_recaps(store)
    except Exception as e:
        log.debug("send_recaps fallito: %s", e)
    return total
