"""Bot Telegram: menu completo cliccabile, donazioni in Telegram Stars in
italiano, classifica, risultati, live e pronostici gratis per tutti.

Imposta:
  - menu a bottoni (inline keyboard): /start o /menu lo apre, ogni funzionalità
    è raggiungibile senza digitare comandi
  - donazioni in ⭐ Telegram Stars (sendInvoice con currency XTR), tutti i
    contenuti sono gratis (niente abbonamenti, lingua solo italiana)

I comandi testuali continuano a funzionare (es. /classifica, /ask <domanda>);
qualsiasi messaggio libero viene passato all'assistente AI (in italiano).
"""
import logging
import time
import unicodedata

import requests

import config
from app import notify, subs
from app.analysis.assistant import answer
from app.analysis.llm import ask_ai
from app.core import kv
from app.i18n import DONATION_OPTIONS, Tr

log = logging.getLogger("telegram")

API = "https://api.telegram.org/bot{token}/{method}"
MAX_MSG = 4096

INTENTS = {"pronostici": "pronostici"}
MARKET_KEY = {"1x2": "market_1x2", "over_under": "market_over_under",
              "btts": "market_btts"}


def _market_label(tr, market):
    key = MARKET_KEY.get(market)
    return tr._t(key) if key else market


# ------------------------------------------------------------------- utils
def _norm(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii",
                                                         "ignore").decode().lower()


def _split_long(text):
    """Divide un messaggio troppo lungo per Telegram in più pezzi (iterativo, no ricorsione)."""
    if len(text) <= MAX_MSG:
        return [text]
    out = []
    while len(text) > MAX_MSG:
        cut = text.rfind("\n", 0, MAX_MSG)
        if cut <= 0:
            cut = MAX_MSG
        out.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        out.append(text)
    return out


def _clean(s):
    s = s.replace("⚠", "").replace("**", "")
    s = "\n".join(l for l in s.splitlines() if l.strip())
    return s.strip()


def _render(result):
    """Trasforma la risposta strutturata dell'assistente (testo)."""
    parts = []
    intro = str(result.get("intro") or "")
    if intro:
        parts.append(_clean(intro))
    for l in result.get("lines") or []:
        if str(l).strip():
            parts.append(_clean(str(l)))
    for it in result.get("items") or []:
        title = _clean(str(it.get("title") or ""))
        text = _clean(str(it.get("text") or ""))
        parts.append(f"• {title}\n  {text}" if text else f"• {title}")
    body = "\n\n".join(parts).strip()
    return body or "Nessun dato disponibile."


def _parse_teams(store):
    """Mappa nome normalizzato -> nome canonico (classifica/risultati/partite)."""
    out = {}
    names = set()
    for r in store.get("standings", []):
        names.add(r.get("name"))
    for rnd in store.get("results", []):
        for m in rnd.get("matches", []):
            names.add(m.get("home"))
            names.add(m.get("away"))
    for f in store.get("fixtures", []):
        names.add(f.get("home"))
        names.add(f.get("away"))
    for n in names:
        if n:
            out[_norm(n)] = n
    return out


# --------------------------------------------------------------- testi dati
def _classifica_text(tr, standings):
    if not standings:
        return tr._t("classifica_nodata")
    rows = sorted(standings, key=lambda x: (x.get("position") or 99))[:20]
    lines = [tr._t("classifica_title"), ""]
    for r in rows:
        lines.append(
            tr._t("classifica_row",
                  pos=r.get("position"), name=r.get("name"),
                  points=r.get("points", 0), played=r.get("played", 0),
                  gf=r.get("gf", 0), ga=r.get("ga", 0)))
    return "\n".join(lines)


def _giornata_text(tr, fixtures):
    if not fixtures:
        return tr._t("partite_nodata")
    lines = [tr._t("partite_title", r=fixtures[0].get("round")), ""]
    for fx in fixtures[:10]:
        p = fx.get("predictions") or {}
        probs = p.get("1x2") or {}
        line = f"{fx.get('home')} - {fx.get('away')}"
        if probs:
            line += (f"  ·  1X2: {probs.get('1', 0) * 100:.0f}%/"
                     f"{probs.get('x', 0) * 100:.0f}%/{probs.get('2', 0) * 100:.0f}%")
        mp = (p.get("model_picks") or {}).get("1x2")
        if mp:
            odds = f", quota {mp['odds']:.2f}" if mp.get("odds") else ""
            line += (f"\n   🎯 {tr._t('pronostico_pick', pick=mp['pick'].upper(), pct=mp['prob'] * 100)}"
                     f"{odds}")
        es = (p.get("exact_score") or [])
        if es:
            line += (f"\n   {tr._t('pronostico_exact', score=es[0]['score'], pct=es[0]['prob'] * 100)}")
        tp = p.get("tipster_mix")
        if tp:
            rate = f"{tp['rate'] * 100:.0f}%" if tp.get("rate") is not None else "n/d"
            src = tp.get("source") or "?"
            o = tp.get("outcome") or "?"
            g = tp.get("goals") or "?"
            s = tp.get("score") or "?"
            line += f"\n   {tr._t('pronostico_tipster', src=src, rate=rate, o=o, g=g, s=s)}"
        best = (p or {}).get("best_bets") or []
        if best:
            b = best[0]
            line += f"\n   • {b.get('pick')} @ {b.get('odds')} ({b.get('prob', 0) * 100:.0f}%)"
        lines.append(line)
        lines.append("")
    return "\n".join(lines).rstrip()


def _risultati_text(tr, results):
    if not results:
        return tr._t("risultati_nodata")
    from app.analysis import morale as morale_mod
    lines = [tr._t("risultati_title"), ""]
    for rnd in results:
        lines.append(tr._t("giornata", r=rnd["round"]))
        for m in rnd["matches"]:
            base = f"  {m['home']} {m['score']} {m['away']}"
            sc = str(m.get("score") or "").split("-")
            if len(sc) == 2:
                try:
                    h, a = int(sc[0].strip()), int(sc[1].strip())
                    d1 = morale_mod.post_morale(h, a, True)[1]
                    d2 = morale_mod.post_morale(h, a, False)[1]
                    base += f"\n      {m['home']}: {d1} · {m['away']}: {d2}"
                except ValueError:
                    pass
            lines.append(base)
        lines.append("")
    return "\n".join(lines).rstrip()


def _live_text(tr, live):
    matches = live.get("matches") or []
    if not matches:
        return tr._t("live_nodata")
    lines = [tr._t("live_title"), ""]
    for m in matches:
        minute = f" · {m['minute']}'" if m.get("minute") is not None else ""
        lines.append(f"{m['home']} {m.get('hs', '-')}-{m.get('as', '-')} "
                     f"{m['away']}{minute}")
    return "\n".join(lines)


def _morale_text(tr, fixtures):
    if not fixtures:
        return tr._t("morale_nodata")
    lines = [tr._t("morale_title", r=fixtures[0].get("round")), ""]
    for fx in fixtures[:12]:
        mo = fx.get("morale") or {}
        h, a = mo.get("home") or {}, mo.get("away") or {}
        if not h and not a:
            continue
        lines.append(f"{fx.get('home')} - {fx.get('away')}")
        for name, m in ((fx.get("home"), h), (fx.get("away"), a)):
            note = (m.get("notes") or [])[:1]
            quote = ("   💬 " + note[0]["title"]) if note else ""
            lines.append(f"  {name}: {m.get('label', '?')} "
                         f"{m.get('score', '?')}/10"
                         f"{' · assenti ' + str(m['injuries']) if m.get('injuries') else ''}")
            if m.get("coach_note"):
                lines.append("   🔁 " + m["coach_note"])
            if quote:
                lines.append(quote)
        lines.append("")
    return "\n".join(lines).rstrip() or tr._t("morale_nodata")


def _tracking_text(tr, tracking):
    if not tracking:
        return tr._t("tracking_empty")
    lines = [tr._t("tracking_title"), ""]
    if tracking.get("bets_total"):
        rate = tracking["bets_rate"]
        lines.append(tr._t("tracking_evaluated", n=tracking["evaluated"]))
        lines.append(tr._t("tracking_hit", hit=tracking["bets_hit"],
                           tot=tracking["bets_total"], pct=rate * 100))
        if tracking.get("match_bets_total"):
            lines.append(tr._t("tracking_match_hit",
                               hit=tracking["match_bets_hit"],
                               tot=tracking["match_bets_total"],
                               pct=tracking["match_bets_rate"] * 100))
        for m, st in sorted((tracking.get("by_market") or {}).items()):
            if st.get("bets_total"):
                lines.append(f"· {_market_label(tr, m)}: "
                             f"{st['bets_hit']}/{st['bets_total']} "
                             f"({st['bets_rate'] * 100:.0f}%)")
        if tracking.get("picks_total"):
            lines.append(f"· Pronostico modello (1X2/Over/BTTS): "
                         f"{tracking['picks_hit']}/{tracking['picks_total']} "
                         f"({tracking['picks_rate'] * 100:.0f}%)")
    if tracking.get("brier") is not None:
        lines.append(tr._t("tracking_brier", b=tracking["brier"]))
    if tracking.get("rps") is not None:
        lines.append(tr._t("tracking_rps", r=tracking["rps"]))
    oos = tracking.get("oos") or {}
    pod = (oos.get("check") or {}).get("picks") or {}
    if (oos.get("brier_calibrated") is not None
            and oos.get("brier") is not None and oos.get("records", 0) >= 2):
        lines.append(tr._t("tracking_oos", b=oos["brier"], bc=oos["brier_calibrated"],
                           imp=(oos.get("improvement") or 0.0)))
        if oos.get("rps") is not None:
            lines.append(tr._t("tracking_oos_rps", r=oos["rps"],
                               rc=oos.get("rps_calibrated") or oos["rps"]))
        ci = oos.get("ci95")
        if ci:
            sig = "✅" if oos.get("significant") else "≈"
            lines.append(tr._t("tracking_oos_ci",
                               imp=(oos.get("improvement") or 0.0),
                               lo=ci["lo"], hi=ci["hi"], p=ci["p_better"], sig=sig))
        if pod.get("total"):
            lines.append(tr._t("tracking_oos_picks", hit=pod["hit"],
                               tot=pod["total"], pct=pod["rate"] * 100))
    lines.append("")
    lessons = tracking.get("conclusions") or []
    if lessons:
        lines.append(tr._t("tracking_learned"))
        lines += lessons[:6]
    return "\n".join(lines)


def _pronostici_note(tr, tracking):
    total = tracking.get("bets_total")
    if not total:
        return None
    return tr._t("pronostici_note", hit=tracking.get("bets_hit"),
                 tot=total, rate=tracking["bets_rate"] * 100)


def _schedina_text(tr, slip):
    if not slip or not slip.get("picks"):
        return tr._t("schedina_nodata")
    from app.core import markets
    lines = [tr._t("schedina_title", r=slip.get("round") or "?"), ""]
    for p in (slip.get("picks") or []):
        pick = markets.label(p.get("market") or "1x2", p.get("pick") or "?")
        odds = p.get("odds") or 0
        pct = (p.get("prob") or 0) * 100
        score = p.get("score") or ""
        lines.append(tr._t("schedina_match", home=p.get("home"),
                           away=p.get("away")))
        if p.get("result") == "win":
            lines.append("   " + tr._t("schedina_win", pick=pick, odds=odds,
                                       pct=pct, score=score))
        elif p.get("result") == "loss":
            lines.append("   " + tr._t("schedina_loss", pick=pick, odds=odds,
                                       pct=pct, score=score))
        else:
            lines.append("   " + tr._t("schedina_pending", pick=pick, odds=odds,
                                       pct=pct))
    wins = sum(1 for p in slip.get("picks", []) if p.get("result") == "win")
    losses = sum(1 for p in slip.get("picks", []) if p.get("result") == "loss")
    lines.append("")
    lines.append(tr._t("schedina_counter", wins=wins, losses=losses))
    hist = slip.get("history") or []
    if hist:
        lines.append("")
        lines.append(tr._t("schedina_history_title"))
        for h in reversed(hist):
            lines.append(tr._t("schedina_history_row", r=h.get("round"),
                               wins=h.get("wins", 0), losses=h.get("losses", 0)))
    return "\n".join(lines)


# ---------------------------------------------------------------- tastiere
def _kb(rows):
    def btn(t, d):
        if d.startswith("http"):
            return {"text": t, "url": d}
        return {"text": t, "callback_data": d}
    return {"inline_keyboard": [
        [btn(t, d) for t, d in row] for row in rows]}


def _menu_kb(tr):
    rows = [
        [(tr._t("menu_classifica"), "p:classifica"),
         (tr._t("menu_partite"), "p:partite")],
        [(tr._t("menu_risultati"), "p:risultati"),
         (tr._t("menu_live"), "p:live")],
        [(tr._t("menu_pronostici"), "p:pronostici"),
         (tr._t("menu_morale"), "p:morale"),
         (tr._t("menu_tracking"), "p:tracking")],
         [(tr._t("menu_schedina"), "p:schedina")],
        [(tr._t("menu_segui"), "flw"),
         (tr._t("menu_stopsegui"), "unf")],
    ]
    if config.PUBLIC_URL:
        rows.append([(tr._t("menu_sito"), config.PUBLIC_URL)])
    rows.append([(tr._t("menu_donazioni"), "don"),
                 (tr._t("menu_menu"), "m")])
    return _kb(rows)


def _don_kb(tr):
    rows = [DONATION_OPTIONS[i:i + 3] for i in range(0, len(DONATION_OPTIONS), 3)]
    buttons = [[("⭐ " + str(s), f"don:{s}") for s in row] for row in rows]
    return _kb(buttons + [[(tr._t("back"), "m")]])


def _teams_kb(store, tr, prefix, teams=None):
    """Tastiera con le squadre (dalla classifica) + bottone Indietro."""
    names = teams
    if names is None:
        names = sorted(
            {r.get("name") for r in store.get("standings", []) if r.get("name")})
    rows = []
    for i in range(0, len(names), 2):
        row = names[i:i + 2]
        rows.append([(n, f"{prefix}:{n}") for n in row])
    if prefix == "unf":
        rows.append([(tr._t("all"), "unf:all")])
    rows.append([(tr._t("back"), "m")])
    return _kb(rows)


class TelegramBot:
    def __init__(self, store, token=config.TELEGRAM_BOT_TOKEN,
                 allowed_ids=None):
        self.store = store
        self.token = token
        self.allowed = set(allowed_ids or config.TELEGRAM_ALLOWED_IDS)
        self.username = None
        self._offset = 0
        self._running = False
        off = kv.read_json("tg_offset.json")
        if isinstance(off, dict) and isinstance(off.get("offset"), int):
            self._offset = off["offset"]
            log.info("Telegram offset ripreso da %d", self._offset)

    # -------------------------------------------------------------- api
    def _call(self, method, payload, timeout=25):
        url = API.format(token=self.token, method=method)
        try:
            r = requests.post(url, json=payload, timeout=timeout)
            data = r.json()
            if not data.get("ok"):
                desc = str(data.get("description") or "")
                log.warning("Telegram %s: %s", method, desc)
                # backoff su flood control di Telegram
                if "Too Many" in desc or "retry after" in desc.lower():
                    import re
                    m = re.search(r"retry after (\d+)", desc.lower())
                    wait = int(m.group(1)) if m else 5
                    log.warning("Telegram flood, attendo %ds", wait)
                    time.sleep(wait)
                return None
            return data.get("result")
        except Exception as e:
            log.warning("Telegram %s: %s", method, e)
            return None

    def _send(self, chat_id, text, reply_markup=None):
        for i, chunk in enumerate(_split_long(text)):
            payload = {"chat_id": chat_id, "text": chunk,
                       "disable_web_page_preview": True}
            if i == 0 and reply_markup is not None:
                payload["reply_markup"] = reply_markup
            if self._call("sendMessage", payload) is None:
                return

    def _send_menu(self, chat_id, text=None):
        tr = Tr(chat_id)
        body = text or tr._t("menu_title")
        if not text:
            body = body + "\n\n" + tr._t("disclaimer")
        self._send(chat_id, body, _menu_kb(tr))

    def _edit(self, chat_id, message_id, text, reply_markup=None):
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self._call("editMessageText", payload)

    def _edit_or_send(self, chat_id, message_id, text, reply_markup=None):
        if message_id and self._edit(chat_id, message_id, text, reply_markup):
            return
        self._send(chat_id, text, reply_markup)

    def _answer_cb(self, callback_id):
        self._call("answerCallbackQuery", {"callback_query_id": callback_id})

    # ------------------------------------------------------- autorizza
    def _authorized(self, chat_id):
        if not self.allowed:
            return True
        return chat_id in self.allowed

    # ----------------------------------------------------------- sezioni
    def _section_text(self, tr, section):
        if section == "classifica":
            return _classifica_text(tr, self.store.get("standings", []))
        if section == "partite":
            return _giornata_text(tr, self.store.get("fixtures", []))
        if section == "risultati":
            return _risultati_text(tr, self.store.get("results", []))
        if section == "live":
            return _live_text(tr, self.store.get("live") or {})
        if section == "morale":
            return _morale_text(tr, self.store.get("fixtures", []))
        if section == "tracking":
            return _tracking_text(tr, self.store.get("tracking", {}))
        if section == "schedina":
            return _schedina_text(tr, self.store.get("schedina") or {})
        if section in INTENTS:
            result = answer(INTENTS[section], self.store.get("fixtures", []))
            return _render(result)
        return tr._t("menu_title")

    def _open_section(self, chat_id, message_id, section):
        tr = Tr(chat_id)
        text = self._section_text(tr, section)
        kb = _menu_kb(tr)
        if section in ("pronostici",):
            note = _pronostici_note(tr, self.store.get("tracking", {}))
            if note and "\n\n" not in text:
                text += "\n\n" + note
            text += "\n\n" + tr._t("disclaimer")
        self._edit_or_send(chat_id, message_id, text, kb)

    # ------------------------------------------------- callback data
    def _on_callback(self, chat_id, callback_id, message_id, data):
        self._answer_cb(callback_id)
        # maint approval: solo capo può approvare
        if data.startswith("maint_ok:") or data.startswith("maint_no:"):
            if chat_id not in config.TELEGRAM_OWNER_IDS:
                self._send(chat_id, "🚫 Solo @Ziosapi può approvare.")
                return
            pid = data.split(":",1)[1]
            try:
                from app import maintenance as maint
                if data.startswith("maint_ok:"):
                    ok, msg = maint.approve_pending(pid)
                    self._edit_or_send(chat_id, message_id, f"✅ {msg} - proposta {pid}", _menu_kb(Tr(chat_id)))
                else:
                    ok, msg = maint.reject_pending(pid)
                    self._edit_or_send(chat_id, message_id, f"❌ {msg} - proposta {pid} cancellata", _menu_kb(Tr(chat_id)))
            except Exception as e:
                self._send(chat_id, f"Errore: {e}")
            return
        if not self._authorized(chat_id):
            return
        tr = Tr(chat_id)
        log.info("Telegram: callback %s da %s", data, chat_id)
        try:
            if data == "m":
                self._edit_or_send(chat_id, message_id,
                                   tr._t("menu_title") + "\n\n"
                                   + tr._t("disclaimer"), _menu_kb(tr))
            elif data.startswith("p:"):
                self._open_section(chat_id, message_id, data[2:])
            elif data == "flw":
                self._edit_or_send(chat_id, message_id, tr._t("segui_prompt"),
                                   _teams_kb(self.store, tr, "flw"))
            elif data.startswith("flw:"):
                self._follow(chat_id, data[4:], message_id)
            elif data == "unf":
                self._show_unfollow(chat_id, message_id)
            elif data.startswith("unf:"):
                self._do_unfollow(chat_id, data[4:], message_id)
            elif data == "don":
                self._edit_or_send(chat_id, message_id, tr._t("don_title"),
                                   _don_kb(tr))
            elif data.startswith("don:"):
                try:
                    stars = int(data[4:])
                except ValueError:
                    stars = 50
                self._edit_or_send(chat_id, message_id,
                                   tr._t("menu_title"), _menu_kb(tr))
                self._send_invoice(chat_id, stars)
        except Exception as e:
            log.error("Telegram: callback %s fallita: %s", data, e)

    # ------------------------------------------------------------- follow
    def _follow(self, chat_id, team, message_id):
        from app.live import _load_follows, add_follow
        tr = Tr(chat_id)
        candidates = _parse_teams(self.store)
        canon = candidates.get(_norm(team), team)
        add_follow(chat_id, [canon])
        cur = ", ".join(_load_follows().get(str(chat_id), []))
        self._edit_or_send(chat_id, message_id,
                           tr._t("segui_ok", teams=cur), _menu_kb(tr))

    def _show_unfollow(self, chat_id, message_id):
        from app.live import _load_follows
        tr = Tr(chat_id)
        followed = _load_follows().get(str(chat_id), [])
        if not followed:
            self._edit_or_send(chat_id, message_id, tr._t("stop_none"),
                               _menu_kb(tr))
            return
        self._edit_or_send(chat_id, message_id, tr._t("stop_prompt"),
                           _teams_kb(self.store, tr, "unf", teams=followed))

    def _do_unfollow(self, chat_id, target, message_id):
        from app.live import remove_follow
        tr = Tr(chat_id)
        if target == "all":
            remove_follow(chat_id)
            text = tr._t("stop_ok_all")
        else:
            removed = remove_follow(chat_id, [target])
            text = tr._t("stop_ok", teams=", ".join(removed)) if removed \
                else tr._t("stop_none")
        self._edit_or_send(chat_id, message_id, text, _menu_kb(tr))

    def _segui(self, chat_id, arg):
        from app.live import _load_follows, add_follow
        tr = Tr(chat_id)
        if not arg:
            self._send(chat_id, tr._t("segui_prompt"),
                       _teams_kb(self.store, tr, "flw"))
            return
        candidates = _parse_teams(self.store)
        found = []
        for t in arg.split(","):
            canon = candidates.get(_norm(t.strip()))
            if canon and canon not in found:
                found.append(canon)
        if not found:
            self._send(chat_id, tr._t("segui_prompt"),
                       _teams_kb(self.store, tr, "flw"))
            return
        add_follow(chat_id, found)
        cur = ", ".join(_load_follows().get(str(chat_id), []))
        self._send(chat_id, tr._t("segui_ok", teams=cur), _menu_kb(tr))

    def _stopsegui(self, chat_id, arg):
        from app.live import _load_follows, remove_follow
        tr = Tr(chat_id)
        followed = _load_follows().get(str(chat_id), [])
        if not arg:
            self._send(chat_id, tr._t("stop_prompt"),
                       _teams_kb(self.store, tr, "unf", teams=followed))
            return
        candidates = _parse_teams(self.store)
        teams = [candidates.get(_norm(t.strip())) for t in arg.split(",")]
        removed = remove_follow(chat_id, [t for t in teams if t])
        text = tr._t("stop_ok", teams=", ".join(removed)) if removed \
            else tr._t("stop_none")
        self._send(chat_id, text, _menu_kb(tr))

    # -------------------------------------------------------------- capo
    def _is_capo(self, chat_id):
        return chat_id in config.TELEGRAM_OWNER_IDS

    def _capo_aiuto(self, chat_id):
        text = (
            "👑 Comandi da Capo (solo per @ziosapi):\n\n"
            "/capo aiuto — questa guida\n"
            "/capo stato — stato istantaneo (allenatori, quote, coupon)\n\n"
            "🎯 PROBABILITÀ (esito più probabile per partita, NIENTE valore):\n"
            "/capo migliori — l'esito vincente più probabile di OGNI partita\n"
            "/capo migliori <N> — le N partite con l'esito più sicuro\n\n"
            "🔁 ALLENATORI (new-manager bounce):\n"
            "/capo coach — elenco registrati\n"
            "/capo coach add <Squadra>|<Allenatore>|<GG/MM/AAAA>\n"
            "  · parto dal nome squadra (opus anche senza diacritici)\n"
            "  · <Allenatore> e <data> opzionali (default: oggi)\n"
            "  es. /capo coach add Fiorentina|Mario Rossi|12/09/2026\n"
            "/capo coach del <Squadra>\n\n"
            "🎟️ ABBONAMENTI:\n"
            "/capo coupon <CODICE> — crea un voucher\n"
            "/capo regala <chat_id> — completo a VITA a quella chat"
        )
        self._send(chat_id, text, _menu_kb(Tr(chat_id)))

    def _capo_stato(self, chat_id):
        from app.analysis import coach as coach_mod
        from app.core import kv
        reg = coach_mod.load()
        teams = reg.get("teams") or {}
        lines = ["👑 Stato del bot:\n"]
        if teams:
            lines.append("🔁 Allenatori registrati:")
            for name, e in teams.items():
                mgr = e.get("manager") or "da rilevare"
                d = coach_mod.days_since(e)
                when = f" · in carica da {d:.0f} giorni" if d is not None else ""
                new = " (NUOVA ERA ✔)" if coach_mod.is_new(e) else ""
                lines.append(f"  · {name}: {mgr}{when}{new}")
        else:
            lines.append("🔁 Nessun allenatore registrato.")
        coupon_n = len(subs._extra_coupons())
        lines.append(f"\n🎟️ Coupon del capo: {coupon_n}")
        lines.append(
            f"\nNota: le modifiche valgono dal prossimo ciclo "
            f"(ogni {config.UPDATE_INTERVAL_SECONDS // 60} min) "
            f"e su Telegram Remote.")
        self._send(chat_id, "\n".join(lines), _menu_kb(Tr(chat_id)))

    def _capo_migliori(self, chat_id, limit=None):
        fixtures = [f for f in self.store.get("fixtures", [])
                    if f.get("status") != "finished"
                    and (f.get("predictions") or {}).get("1x2")]
        if not fixtures:
            self._send(chat_id, "Nessuna partita con pronostico disponibile.",
                       _menu_kb(Tr(chat_id)))
            return
        fixtures.sort(key=lambda f: f.get("start_ts") or 0)
        rows = []
        for fx in fixtures:
            probs = fx["predictions"]["1x2"]
            pick = max(("1", "x", "2"), key=lambda k: probs.get(k, 0))
            p = probs.get(pick, 0)
            fair = 1 / p if p > 0 else 0
            if pick == "1":
                label = f"1 · {fx.get('home')}"
            elif pick == "2":
                label = f"2 · {fx.get('away')}"
            else:
                label = "X · Pareggio"
            when = time.strftime("%a %d/%m %H:%M",
                                 time.localtime(fx.get("start_ts") or 0))
            rows.append({
                "sort": p,
                "text": f"🕐 {when} · {fx.get('home')} - {fx.get('away')}\n"
                        f"   🎯 {label}  —  probabilità {p*100:.0f}%  "
                        f"(fair {fair:.2f})\n"
                        f"   📊 1X2: {probs.get('1',0)*100:.0f}/"
                        f"{probs.get('x',0)*100:.0f}/{probs.get('2',0)*100:.0f}%"})
        if limit:
            rows.sort(key=lambda r: r["sort"], reverse=True)
            rows = rows[:limit]
        else:
            rows.sort(key=lambda r: r["sort"], reverse=False)
        head = "🎯 Miglior esito per PROBABILITÀ (modello, non valore):\n\n"
        text = head + "\n\n".join(r["text"] for r in rows)
        self._send(chat_id, text, _menu_kb(Tr(chat_id)))

    def _capo_coach(self, chat_id, arg):
        self._send(chat_id, Tr(chat_id)._t("ai_thinking"))
        from app.analysis import coach as coach_mod
        tr = Tr(chat_id)
        action = _norm(arg.split(" ", 1)[0]) if arg.strip() else ""
        if not arg.strip():
            self._send(chat_id, self._capo_coach_list(), _menu_kb(tr))
            return
        if action in ("del", "remove", "rimuovi"):
            rest = arg.split(" ", 1)[1].strip() if " " in arg.strip() else ""
            if not rest:
                self._send(chat_id, self._capo_coach_list(), _menu_kb(tr))
                return
            reg = coach_mod.load()
            teams = reg.get("teams") or {}
            names_map = _parse_teams(self.store)
            canon = names_map.get(_norm(rest)) or rest
            if canon not in teams:
                self._send(chat_id, f"Se non vedo {canon} nel registro, "
                           "nulla da rimuovere.", _menu_kb(tr))
                return
            del teams[canon]
            coach_mod.save(reg)
            self._send(chat_id, f"✅ {canon}: rimosso dal registro allenatori.",
                       _menu_kb(tr))
            return
        if action in ("add", "set", "adds"):
            fields = arg.split(" ", 1)[1].strip().split("|") if " " in arg.strip() else []
            if not fields or len(fields) > 3:
                self._send(chat_id,
                           "Formato: /capo coach add Squadra|Allenatore|GG/MM/AAAA",
                           _menu_kb(tr))
                return
            team_raw = fields[0].strip() if fields else ""
            names_map = _parse_teams(self.store)
            canon = names_map.get(_norm(team_raw)) or team_raw
            if not canon:
                self._send(chat_id,
                           f"❓ Squadra '{team_raw}' non riconosciuta: "
                           "usala con il nome esatto (es. AC Milan).",
                           _menu_kb(tr))
                return
            mgr = ""
            since_ts = None
            if len(fields) >= 2 and fields[1].strip():
                mgr = fields[1].strip()
            if len(fields) >= 3 and fields[2].strip():
                date = fields[2].strip()
                try:
                    import datetime
                    since_ts = int(datetime.datetime.strptime(
                        date, "%d/%m/%Y").timestamp())
                except ValueError:
                    self._send(chat_id,
                               f"⚠️ Data '{date}' non valida (user DD/MM/YYYY), "
                               "uso oggi.", _menu_kb(tr))
            reg = coach_mod.load()
            teams = reg.setdefault("teams", {})
            entry = teams.get(canon) or {}
            tid = None
            for r in self.store.get("standings", []):
                if r.get("name") == canon:
                    tid = r.get("team_id")
                    break
            entry.update({
                "team_id": tid or entry.get("team_id"),
                "manager": mgr or entry.get("manager"),
                "since": since_ts if since_ts is not None
                else int(time.time()),
                "source": "capo",
                "note": "Registrato dal Capo via Telegram",
            })
            teams[canon] = entry
            coach_mod.save(reg)
            self._send(chat_id,
                       f"✅ {canon}: nuovo allenatore registrato"
                       f"{(' (' + mgr + ')') if mgr else ' (nome da rilevare)'} — "
                       "nuova era attiva per 30 giorni.", _menu_kb(tr))
            return
        self._send(chat_id, self._capo_coach_list(), _menu_kb(tr))

    def _capo_coach_list(self):
        from app.analysis import coach as coach_mod
        reg = coach_mod.load()
        teams = reg.get("teams") or {}
        if not teams:
            return "Registro allenatori vuoto (nessuna nuova era)."
        lines = ["Registro allenatori (new-manager bounce):"]
        for name, e in teams.items():
            mgr = e.get("manager") or "da rilevare"
            d = coach_mod.days_since(e)
            when = f" · era in carica da {d:.0f} giorni" if d is not None else ""
            new = " · NUOVA ERA ✔" if coach_mod.is_new(e) else ""
            lines.append(f"  · {name}: {mgr}{when}{new}")
        return "\n".join(lines)

    def _capo_coupon(self, chat_id, arg):
        tr = Tr(chat_id)
        code = arg.strip().strip()
        if not code:
            self._send(chat_id, "Uso: /capo coupon <CODICE>",
                       _menu_kb(tr))
            return
        if subs.add_coupon(code):
            self._send(chat_id, f"🎟️ Coupon '{code}' creato: i fan possono "
                       "scriverlo in chat (o /coupon CODICE) per il completo "
                       "a VITA.", _menu_kb(tr))
        else:
            self._send(chat_id, f"ℹ️ '{code}' esiste già.",
                       _menu_kb(tr))

    def _capo_regala(self, chat_id, arg):
        tr = Tr(chat_id)
        target = arg.strip()
        try:
            target_id = int(target)
        except (TypeError, ValueError):
            self._send(chat_id, "Uso: /capo regala <chat_id numerico>",
                       _menu_kb(tr))
            return
        if target_id == chat_id:
            self._send(chat_id, "👑 Sei già il Capo, non serve.",
                       _menu_kb(tr))
            return
        subs.grant_lifetime(target_id)
        self._send(chat_id, f"🎁 Chat {target_id}: completo ⭐ a VITA regalato!",
                   _menu_kb(tr))

    def _handle_capo(self, chat_id, text):
        if not self._is_capo(chat_id):
            self._send(chat_id, "🚫 Comando riservato al Capo.",
                       _menu_kb(Tr(chat_id)))
            return
        args = text.split(maxsplit=1)
        rest = (args[1] if len(args) > 1 else "").strip()
        action = _norm(rest.split(" ", 1)[0]) if rest else ""
        if not rest or action in ("aiuto", "help", "?"):
            self._capo_aiuto(chat_id)
        elif action == "stato":
            self._capo_stato(chat_id)
        elif action == "migliori":
            nxt = rest.split(" ", 1)[1].strip() if " " in rest else ""
            try:
                limit = int(nxt) if nxt else None
            except ValueError:
                limit = None
            self._capo_migliori(chat_id, limit)
        elif action == "coach":
            nxt = rest.split(" ", 1)[1].strip() if " " in rest else ""
            self._capo_coach(chat_id, nxt)
        elif action == "coupon":
            nxt = rest.split(" ", 1)[1].strip() if " " in rest else ""
            self._capo_coupon(chat_id, nxt)
        elif action == "regala":
            nxt = rest.split(" ", 1)[1].strip() if " " in rest else ""
            self._capo_regala(chat_id, nxt)
        else:
            self._capo_aiuto(chat_id)

    # -------------------------------------------------------------- AI
    def _ask(self, chat_id, question):
        tr = Tr(chat_id)
        self._send(chat_id, tr._t("ai_thinking"))
        fixtures = self.store.get("fixtures", [])
        standings = self.store.get("standings", [])
        result = ask_ai(question, fixtures, standings)
        if result is None:
            result = answer(question, fixtures)
        self._send(chat_id, _render(result), _menu_kb(tr))

    # ---------------------------------------------------------- donazioni
    def _send_invoice(self, chat_id, stars):
        tr = Tr(chat_id)
        payload = {
            "chat_id": chat_id,
            "title": tr._t("menu_donazioni").replace("⭐ ", ""),
            "description": "Serie A Stats",
            "payload": f"don-{chat_id}-{int(time.time())}",
            "provider_token": "",
            "currency": "XTR",
            "prices": [{"label": "⭐ Telegram Stars", "amount": int(stars)}],
            "start_parameter": "seriea-stats",
        }
        if self._call("sendInvoice", payload) is None:
            log.warning("Telegram: fattura %d stelle rifiutata per %s",
                        stars, chat_id)

    def _on_precheckout(self, query_id):
        self._call("answerPreCheckoutQuery",
                   {"pre_checkout_query_id": query_id, "ok": True})

    def _on_successful_payment(self, chat_id, payment, payload=""):
        tr = Tr(chat_id)
        stars = payment.get("total_amount") or 0
        # payload opzionale per verifica futura (invoice_payload)
        if payload:
            log.info("Telegram: pagamento verificato payload %s", payload)
        self._send(chat_id, tr._t("don_thanks", stars=stars), _menu_kb(tr))

    # ------------------------------------------------------------ comandi
    def _handle_command(self, chat_id, text):
        q = _norm(text)
        if text.startswith("/start") or text.startswith("/help") \
                or text.startswith("/menu"):
            if text.startswith("/start"):
                notify.register_started(chat_id)
            self._send_menu(chat_id)
        elif text.startswith("/classifica"):
            tr = Tr(chat_id)
            self._send(chat_id,
                       _classifica_text(tr, self.store.get("standings", [])),
                       _menu_kb(tr))
        elif text.startswith("/giornata") or text.startswith("/partite"):
            tr = Tr(chat_id)
            self._send(chat_id,
                       _giornata_text(tr, self.store.get("fixtures", [])),
                       _menu_kb(tr))
        elif text.startswith("/risultati") or text.startswith("/gare"):
            tr = Tr(chat_id)
            self._send(chat_id,
                       _risultati_text(tr, self.store.get("results", [])),
                       _menu_kb(tr))
        elif text.startswith("/live"):
            tr = Tr(chat_id)
            self._send(chat_id,
                       _live_text(tr, self.store.get("live") or {}),
                       _menu_kb(tr))
        elif text.startswith("/segui"):
            self._segui(chat_id, text[6:].strip())
        elif text.startswith("/stopsegui"):
            self._stopsegui(chat_id, text[10:].strip())
        elif text.startswith("/donazioni") or text.startswith("/don"):
            tr = Tr(chat_id)
            self._send(chat_id, tr._t("don_title"), _don_kb(tr))
        elif text.startswith("/tracking") or text.startswith("/onesta") \
                or text.startswith("/onestà") or text.startswith("/statistiche"):
            tr = Tr(chat_id)
            self._send(chat_id,
                       _tracking_text(tr, self.store.get("tracking", {})),
                       _menu_kb(tr))
        elif text.startswith("/schedina"):
            tr = Tr(chat_id)
            self._send(chat_id,
                       _schedina_text(tr, self.store.get("schedina") or {}),
                       _menu_kb(tr))
        elif text.startswith("/pronostici") or text.startswith("/bet"):
            tr = Tr(chat_id)
            result = answer("pronostici", self.store.get("fixtures", []))
            body = _render(result)
            note = _pronostici_note(tr, self.store.get("tracking", {}))
            if note:
                body += "\n\n" + note
            self._send(chat_id, body, _menu_kb(tr))
        elif text.startswith("/ask"):
            question = text[4:].strip() or "pronostici della giornata"
            self._ask(chat_id, question)
        elif text.startswith("/capo"):
            self._handle_capo(chat_id, text)
        elif text.startswith("/coupon"):
            code = text[7:].strip()
            tr = Tr(chat_id)
            if subs.redeem_coupon(chat_id, code):
                self._send(chat_id, tr._t("subs_coupon_ok"), _menu_kb(tr))
            else:
                self._send(chat_id, tr._t("subs_coupon_bad"), _menu_kb(tr))
        elif text.startswith("/opencode") or text.startswith("/fix") or text.startswith("/code"):
            if chat_id not in config.TELEGRAM_OWNER_IDS:
                self._send(chat_id, "🚫 Solo @Ziosapi può usare /opencode.")
                return
            req = text.split(None, 1)[1].strip() if len(text.split(None, 1)) > 1 else ""
            if not req:
                self._send(chat_id, "Usa: /opencode <descrizione fix>", _menu_kb(Tr(chat_id)))
                return
            from app import maintenance as maint
            from app.analysis import codegen
            self._send(chat_id, f"⏳ Elaboro: {req} ...")
            try:
                changes = codegen.generate_fix(req)
            except Exception as e:
                self._send(chat_id, f"❌ Errore LLM: {e}", _menu_kb(Tr(chat_id)))
                return
            if not changes:
                self._send(chat_id, "❌ LLM non ha prodotto modifiche valide.", _menu_kb(Tr(chat_id)))
                return
            file_list = ", ".join(c.get("path", "?") for c in changes)
            ok_apply = maint._apply_fixes(changes)
            if not ok_apply:
                self._send(chat_id, "❌ Errore applicazione fix.", _menu_kb(Tr(chat_id)))
                return
            ok_push, push_msg = maint._git_push("fix: %s" % req, files=[c["path"] for c in changes])
            status = "✅" if ok_push else "⚠️"
            self._send(chat_id, f"{status} Applicato: {file_list}\n{push_msg}", _menu_kb(Tr(chat_id)))
        else:
            self._send_menu(chat_id)

    # ------------------------------------------------------------ loop
    def start(self):
        if not self.token:
            log.warning("Telegram: nessun token (config.TELEGRAM_BOT_TOKEN)")
            return
        self._running = True
        me = self._call("getMe", {})
        if me and me.get("username"):
            self.username = "@" + me["username"]
            log.info("Telegram bot %s online", self.username)
            try:
                self.store.set("tg_username", self.username)
                self.store.save()
            except Exception:
                pass
        while self._running:
            updates = self._call("getUpdates",
                                 {"timeout": 30, "offset": self._offset},
                                 timeout=40)
            if not updates:
                time.sleep(1)
                continue
            for u in updates:
                self._process(u)
                self._offset = u["update_id"] + 1
                kv.write_json("tg_offset.json", {"offset": self._offset})

    def stop(self):
        self._running = False

    # ----------------------------------------------------------- process
    def _process(self, update):
        cb = update.get("callback_query") or {}
        if cb:
            chat = (cb.get("message") or {}).get("chat") or {}
            chat_id = chat.get("id")
            if chat_id:
                self._on_callback(chat_id, cb.get("id"),
                                  (cb.get("message") or {}).get("message_id"),
                                  cb.get("data") or "")
            return

        pck = update.get("pre_checkout_query") or {}
        if pck:
            self._on_precheckout(pck.get("id"))
            return

        msg = update.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        if not chat_id:
            return
        if not self._authorized(chat_id):
            log.info("Telegram: chat %s non autorizzata", chat_id)
            return

        payment = msg.get("successful_payment") or {}
        if payment:
            log.info("Telegram: pagamento %s da %s: %s stelle",
                     msg.get("invoice_payload"), chat_id,
                     payment.get("total_amount"))
            self._on_successful_payment(chat_id, payment,
                                        msg.get("invoice_payload") or "")
            return

        text = (msg.get("text") or "").strip()
        if not text:
            return
        log.info("Telegram: messaggio da %s: %r", chat_id, text[:120])
        # comandi approvazione maintenance: ok / rifiuta (solo capo)
        low = text.strip().lower()
        if low in ("ok", "rifiuta", "rifiuto") and chat_id in config.TELEGRAM_OWNER_IDS:
            try:
                from app import maintenance as maint
                state = maint._read()
                pending = state.get("pending_proposal")
                if not pending:
                    self._send(chat_id, "Nessuna proposta in attesa.")
                    return
                pid = pending.get("id")
                if low == "ok":
                    ok, msg2 = maint.approve_pending(pid)
                    self._send(chat_id, f"✅ {msg2} - {pid}", _menu_kb(Tr(chat_id)))
                else:
                    ok, msg2 = maint.reject_pending(pid)
                    self._send(chat_id, f"❌ {msg2} - {pid} cancellata", _menu_kb(Tr(chat_id)))
                return
            except Exception as e:
                self._send(chat_id, f"Errore: {e}")
                return
        try:
            if text.startswith("/"):
                self._handle_command(chat_id, text)
            else:
                self._ask(chat_id, text)
        except Exception as e:
            log.error("Telegram: gestione messaggio fallita: %s", e)


def run(store, token=config.TELEGRAM_BOT_TOKEN):
    bot = TelegramBot(store, token=token)
    bot.start()
