"""Monitor risultati live + notifiche Telegram opzionali.

Risultati live (super veloci): un poller dedicato richiede SOLO
`sport/football/events/live` (una chiamata: tutte le competizioni, filtrate su
Serie A) ogni LIVE_POLL_SECONDS secondi e scrive uno snapshot minimo in Store
(`live`), letto dalla dashboard ogni ~10 s via GET /api/live.

Notifiche: solo per le partite "seguite" con /segui <squadra> su Telegram.
Quando la squadra segna (punteggio cambiato) o la partita finisce, parte un
messaggio. Gli eventi (marcatore) vengono letti solo al cambio risultato,
così il polling resta fulmineo.
"""
import logging
import threading
import time

import requests

import config
from app.core import kv

log = logging.getLogger("live")

_send_lock = threading.Lock()


def _load_follows():
    """chat_id -> [squadre seguite]."""
    data = kv.read_json("follows.json")
    return data if isinstance(data, dict) else {}


def _save_follows(data):
    kv.write_json("follows.json", data)


def add_follow(chat_id, teams):
    follows = _load_follows()
    key = str(chat_id)
    cur = follows.setdefault(key, [])
    added = []
    for t in teams:
        if t and t not in cur:
            cur.append(t)
            added.append(t)
    _save_follows(follows)
    return added


def remove_follow(chat_id, teams=None):
    follows = _load_follows()
    key = str(chat_id)
    cur = follows.get(key, [])
    if teams is None:
        follows[key] = []
        removed = cur
    else:
        removed = [t for t in teams if t in cur]
        follows[key] = [t for t in cur if t not in teams]
    _save_follows(follows)
    return removed


def telegram_send(chat_id, text):
    if not config.TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        with _send_lock:
            requests.post(url, json={"chat_id": chat_id, "text": text,
                                     "disable_web_page_preview": True},
                          timeout=15)
    except Exception as e:
        log.warning("notifica a %s fallita: %s", chat_id, e)


def notify_team(team, text):
    """Invia `text` a tutte le chat che seguono `team`."""
    for chat_id, teams in _load_follows().items():
        if team in teams:
            telegram_send(chat_id, text)


class LiveMonitor:
    def __init__(self, store):
        self.store = store
        self.client = None
        self._stop = threading.Event()
        self._snapshot = {}          # event_id -> dict (stato precedente)

    def start(self):
        thread = threading.Thread(target=self._loop, daemon=True)
        thread.start()
        return self

    def stop(self):
        self._stop.set()

    # ---------------------------------------------------------- ciclo
    def _loop(self):
        log.info("monitor live avviato (ogni %ds)", config.LIVE_POLL_SECONDS)
        while not self._stop.is_set():
            t0 = time.time()
            try:
                self.tick()
            except Exception as e:
                log.exception("monitor live: errore nel ciclo: %s", e)
            elapsed = time.time() - t0
            wait = max(5, config.LIVE_POLL_SECONDS - elapsed)
            self._stop.wait(wait)

    def _get_client(self):
        if self.client is None:
            from app.sources.client import FootballClient
            self.client = FootballClient()
        return self.client

    # ---------------------------------------------------------- tick
    def tick(self):
        client = self._get_client()
        matches = client.live_events()
        changed = []
        finished_now = []
        key = lambda m: m["id"]
        prev = self._snapshot

        for m in matches:
            eid = key(m)
            old = prev.get(eid)
            if old is None:
                changed.append(("start", m, None))
            else:
                if old.get("hs") != m.get("hs") or old.get("as") != m.get("as"):
                    changed.append(("goal", m, old))
                if old.get("status") != "finished" and m.get("status") == "finished":
                    finished_now.append(m)
            prev[eid] = m

        # partite che non sono più live (sparite dall'elenco -> finite)
        for eid in list(prev.keys()):
            if eid not in matches and self._gone_live(eid):
                gone = prev[eid]
                if gone.get("status") != "finished":
                    finished_now.append(gone)
                prev.pop(eid)

        self._snapshot = prev
        self.store.set("live", {
            "updated": int(time.time()),
            "matches": sorted(matches, key=lambda m: (m.get("hs") or 0, m.get("as") or 0), reverse=True),
        })

        # partite finite adesso: valuta subito il pronostico e aggiorna
        # l'["onestà del modello"], invece di aspettare il prossimo ciclo
        if finished_now:
            self._eval_finished([m["id"] for m in finished_now])

        if config.TELEGRAM_BOT_TOKEN:
            self._notify(changed, finished_now)

    def _eval_finished(self, event_ids):
        """Ricalcola l'autocritica appena una partita in diretta finisce.

        Il monitor live vede il "finished" in ~30s dal fischio finale: invece
        di lasciare il pronostico non valutato fino al prossimo ciclo dello
        scheduler (~2.5h dopo l'inizio), lo valuta subito e pubblica tracking
        + calibrazione, così dashboard e bot mostrano l'onestà aggiornata.
        """
        try:
            from app.analysis import tracker
            client = self._get_client()
            changed = tracker.evaluate(client, force_ids=event_ids)
            if not changed:
                return
            tracking, calibration = tracker.analyze()
            self.store.set("tracking", tracking)
            self.store.set("calibration", calibration)
            self.store.save()
            log.info("tracker: onestà aggiornata a fine partita (%d nuovi)",
                     changed)
        except Exception as e:
            log.debug("tracker live update fallito: %s", e)

    def _gone_live(self, event_id):
        """Un'evento live che sparisce = partita finita (o interrotta).

        Verifichiamo con il dettaglio evento per non dare falsi 'finali'."""
        try:
            detail = self._get_client().event_detail(event_id)
            if not detail:
                return False
            return detail.get("status") == "finished"
        except Exception:
            return False

    # ------------------------------------------------------- notifiche
    def _notify(self, changed, finished_now):
        goals = [(kind, m, old) for kind, m, old in changed if kind == "goal"]
        starts = [(kind, m, old) for kind, m, old in changed if kind == "start"]

        for _, m, _ in starts:
            notify_team(m["home"], f"🔴 In diretta! {m['home']} - {m['away']} {_live_score(m)} ({m['period'].lower()})")
            notify_team(m["away"], f"🔴 In diretta! {m['home']} - {m['away']} {_live_score(m)} ({m['period'].lower()})")

        for m in finished_now:
            notify_team(m["home"],
                        f"🏁 FINALE: {m['home']} {m.get('hs')}-{m.get('as')} {m['away']}")
            notify_team(m["away"],
                        f"🏁 FINALE: {m['home']} {m.get('hs')}-{m.get('as')} {m['away']}")

        for _, m, _ in goals:
            minute = m.get("minute") or "?"
            notify_team(m["home"],
                        f"⚽ GOL! {m['home']} {m.get('hs')}-{m.get('as')} {m['away']} · {minute}'")
            notify_team(m["away"],
                        f"⚽ GOL! {m['home']} {m.get('hs')}-{m.get('as')} {m['away']} · {minute}'")


def _live_score(m):
    return f"{m.get('hs')}-{m.get('as')}"