"""Schedina della giornata: la "giocata" una volta per turno.

Costruita PRIMA dell'inizio della prima partita del turno, pesca gli esiti
più probabili di ogni mercato del modello (1X2, Over/Under 2.5, BTTS), un
esito per mercato su partite diverse. A fine partite valuta ogni esito,
aggiorna il contatore vinti/persi e archivia lo storico per giornata.

Le notifiche "pronostico indovinato" (foto) partono ESCLUSIVAMENTE dagli
esiti di questa schedina, inclusi quelli archiviati ma non ancora notificati.
"""
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import config
from app.core import markets

log = logging.getLogger("schedina")

MATCHDAY_WINDOW = 4 * 86400   # la giornata dura al massimo ~96h (ven-lun)


def current_round(store):
    """Numero della giornata corrente, derivato dalla classifica.

    ESPN non espone il numero di giornata: lo ricaviamo dalle partite già
    giocate (max ``played`` in classifica + 1)."""
    played = [(r.get("played") or 0) for r in store.get("standings", [])]
    return int(max(played) + 1) if played else None


# ---------- selezione esiti diversificata --------------------------------
def _candidates(now_fx):
    """Un candidato per mercato e partita: il pick più probabile del modello.

    Usa ``model_picks`` (sempre presenti) invece dei ``best_bets`` (che
    richiedono quota di mercato + edge e di fatto escludono O/U e BTTS). La
    quota esposta è quella reale se disponibile, altrimenti la fair (1/p)."""
    out = []
    for fx in now_fx:
        mp = (fx.predictions or {}).get("model_picks") or {}
        for market in ("1x2", "over_under", "btts"):
            p = mp.get(market)
            if not p:
                continue
            prob = p.get("prob") or 0
            if prob < config.SCHEDINA_MIN_PROB:
                continue
            real_odds = p.get("odds")
            out.append({
                "fixture_id": fx.id, "home": fx.home, "away": fx.away,
                "start_ts": fx.start_ts, "market": market,
                "pick": p.get("key") or p.get("pick"),
                "odds": real_odds or p.get("fair"),
                "prob": prob,
                "edge": round(prob * real_odds - 1, 3) if real_odds else None,
            })
    return out


def _select(cands, max_picks):
    """Prende un esito per mercato (diversificato) dalle partite migliori."""
    by_mkt = {}
    for c in cands:
        by_mkt.setdefault(c["market"], []).append(c)
    for m in by_mkt:
        by_mkt[m].sort(key=lambda c: c["prob"], reverse=True)
    picked, used = [], set()
    markets_order = [m for m in ("1x2", "over_under", "btts")
                     if m in by_mkt]
    while len(picked) < max_picks:
        added = False
        for m in markets_order:
            for c in by_mkt[m]:
                if c["fixture_id"] in used:
                    continue
                picked.append(c)
                used.add(c["fixture_id"])
                by_mkt[m].remove(c)
                added = True
                break
            if len(picked) >= max_picks:
                break
        if not added:
            break
    return picked


def _summary_record(slip):
    """Copia la schedina in una voce d'archivio con il conteggio finale."""
    picks = [dict(p) for p in slip.get("picks") or []]
    return {
        "round": slip.get("round"), "created_at": slip.get("created_at"),
        "picks": picks, "wins": _counts(picks)[0], "losses": _counts(picks)[1],
    }


def _counts(picks):
    picks = picks or []
    return (sum(1 for p in picks if p.get("result") == "win"),
            sum(1 for p in picks if p.get("result") == "loss"))


def _slips(store):
    """La schedina corrente + quelle archiviate (per valutare/notificare)."""
    cur = store.get("schedina") or {}
    hist = (cur.get("history") or []) if cur else []
    out = []
    for entry in ([{"round": cur.get("round"), "picks": cur.get("picks") or []}]
                  + [{"round": h.get("round"), "picks": h.get("picks") or []}
                     for h in hist]):
        if entry["picks"]:
            out.append(entry)
    return out


# ------------------------------------------------------------------- build
def build(store, now_fx):
    """Crea la schedina del turno se non esiste già e le partite non sono
    ancora iniziate. Archivia la schedina del turno precedente."""
    now = time.time()
    upcoming = [f for f in now_fx if (f.start_ts or 0) > now]
    if not upcoming:
        return store.get("schedina") or {}
    upcoming.sort(key=lambda f: f.start_ts)
    rnd = current_round(store)
    cur = store.get("schedina") or {}
    if cur.get("round") == rnd and cur.get("picks"):
        return cur

    # la finestra di 10 giorni di next_fixtures può spanciare due turni:
    # seleziona solo le partite della prima giornata in arrivo
    from_ts = upcoming[0].start_ts
    in_round = [f for f in upcoming if f.start_ts - from_ts < MATCHDAY_WINDOW]

    picks = _select(_candidates(in_round), config.SCHEDINA_MAX_PICKS)
    if not picks:
        return cur

    history = list(cur.get("history", []))
    if cur.get("round") and cur.get("picks"):
        history.append(_summary_record(cur))
    history = history[-config.SCHEDINA_MAX_HISTORY:]

    slip = {"round": rnd, "created_at": int(now),
            "picks": picks, "history": history}
    store.set("schedina", slip)
    log.info("schedina giornata %s: %d esiti (%s)", rnd, len(picks),
             " · ".join(f"{p['pick']}@{p['odds']}" for p in picks))
    return slip


# ---------------------------------------------------------------- evaluate
def evaluate(store, client=None):
    """Valuta gli esiti pendenti (schedina corrente + archivio) usando i
    risultati in store (fallback: dettaglio evento via client)."""
    slip = store.get("schedina")
    scores = {}
    for rnd in (store.get("results") or []):
        for m in (rnd.get("matches") or []):
            hs, as_ = m.get("hs"), m.get("as")
            if hs is not None and as_ is not None:
                scores[m.get("id")] = (hs, as_)
    changed = False
    for entry in _slips(store):
        for p in entry.get("picks") or []:
            if p.get("result"):
                continue
            score = scores.get(p.get("fixture_id"))
            if score is None and client is not None:
                try:
                    d = client.event_detail(p.get("fixture_id"))
                    if d and d.get("status") == "finished" \
                            and d.get("home_score") is not None:
                        score = (d.get("home_score"), d.get("away_score"))
                except Exception:
                    pass
            if score is None:
                continue
            hs, as_ = score
            actual = markets.match_outcomes(hs, as_)
            p["score"] = f"{hs}-{as_}"
            p["result"] = "win" if actual.get(p.get("market")) == p.get("pick") \
                else "loss"
            p["evaluated_at"] = int(time.time())
            changed = True
            log.info("schedina giornata %s: %s-%s %s vs %s -> %s",
                     entry.get("round"), p.get("home"), p.get("away"),
                     p.get("pick"), p.get("score"), p.get("result"))
    if changed:
        # aggiorna i contatori delle voci d'archivio
        for h in (slip.get("history") or []):
            w, l = _counts(h.get("picks"))
            if h.get("wins") != w or h.get("losses") != l:
                h["wins"], h["losses"] = w, l
                changed = True
        store.set("schedina", slip)
    return changed


# ------------------------------------------------------- notifiche foto
def pending_wins(store):
    """Esiti vinti non ancora notificati (foto), corrente + archivio."""
    out = []
    for entry in _slips(store):
        rnd = entry.get("round")
        for p in entry.get("picks") or []:
            if p.get("result") == "win" and not p.get("win_notified"):
                out.append({
                    "id": f"sch-{rnd}-{p.get('fixture_id')}",
                    "round": rnd, "home": p.get("home"), "away": p.get("away"),
                    "score": p.get("score"),
                    "hits": [{"pick": p.get("pick"), "prob": p.get("prob"),
                              "odds": p.get("odds")}],
                })
    return out


def mark_wins_notified(store, ids):
    """Segna come notificati gli esiti vinti (evita doppie foto)."""
    ids = set(ids or ())
    if not ids:
        return
    slip = store.get("schedina")
    if not slip:
        return
    changed = False
    for entry in _slips(store):
        rnd = entry.get("round")
        for p in entry.get("picks") or []:
            if f"sch-{rnd}-{p.get('fixture_id')}" in ids \
                    and p.get("result") == "win":
                p["win_notified"] = True
                changed = True
    if changed:
        store.set("schedina", slip)


if __name__ == "__main__":
    # self-check: selezione diversificata + valutazione esito + archivio
    class _Store(dict):
        def __init__(self, data=None):
            super().__init__(data or {})
        def get(self, k, default=None):
            return super().get(k, default)
        def set(self, k, v):
            self[k] = v

    class _Fx:
        def __init__(self, fid, home, away, start_ts, picks):
            self.id, self.home, self.away = fid, home, away
            self.start_ts, self.round = start_ts, None
            self.predictions = {"model_picks": picks}

    now = time.time()
    fx = [
        _Fx("a", "A", "B", now + 1000, {
            "1x2": {"key": "1", "prob": 0.7, "odds": 1.5},
            "over_under": {"key": "over_2.5", "prob": 0.65, "odds": None},
            "btts": {"key": "no", "prob": 0.52, "odds": None}}),
        _Fx("b", "C", "D", now + 2000, {
            "1x2": {"key": "x", "prob": 0.6, "odds": 2.3},
            "over_under": {"key": "over_2.5", "prob": 0.55, "odds": 1.8},
            "btts": {"key": "si", "prob": 0.51, "odds": None}}),
        _Fx("c", "E", "F", now + 3000, {
            "1x2": {"key": "2", "prob": 0.48, "odds": None},
            "over_under": {"key": "under_2.5", "prob": 0.9, "odds": None},
            "btts": {"key": "si", "prob": 0.95, "odds": 2.0}}),
    ]
    st = _Store({"standings": [{"played": 3} for _ in range(10)]})
    slip = build(st, fx)
    assert slip["round"] == 4, slip
    # diversificati: un mercato diverso per i primi esiti
    mkts = [p["market"] for p in slip["picks"]]
    assert "over_under" in mkts and "1x2" in mkts, mkts
    # valutazione: "a" finisce 1-1, "b" finisce 3-2
    st.set("results", [{"round": 4, "matches": [
        {"id": "a", "hs": 1, "as": 1}, {"id": "b", "hs": 3, "as": 2}]}])
    assert evaluate(st) is True
    a = next(p for p in slip["picks"] if p["fixture_id"] == "a")
    assert a["result"] == "loss", a  # 1-1 vs pick "1" (1x2)
    bwin = next(p for p in slip["picks"]
                if p["fixture_id"] == "b" and p["market"] == "btts")
    assert bwin["result"] == "win", bwin  # 3-2 vs "si" (BTTS)
    # la vincita di "b" è notificabile una sola volta
    assert len(pending_wins(st)) == 1, pending_wins(st)
    mark_wins_notified(st, [w["id"] for w in pending_wins(st)])
    assert pending_wins(st) == []
    # notifiche: "si" di "c" valutato al turno dopo non si perde mai
    fx2 = [_Fx("d", "G", "H", now + 8 * 86400, {
        "1x2": {"key": "1", "prob": 0.6, "odds": 1.7},
        "over_under": {"key": "under_2.5", "prob": 0.55, "odds": 1.8},
        "btts": {"key": "no", "prob": 0.51, "odds": None}})]
    st.set("standings", [{"played": 4} for _ in range(10)])
    slip2 = build(st, fx2)
    assert slip2["round"] == 5, slip2
    assert len(slip2["history"]) == 1, slip2
    print("schedina self-check OK")