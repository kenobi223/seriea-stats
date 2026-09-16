"""Schedina della giornata: la "giocata" una volta per turno.

Costruita PRIMA dell'inizio della prima partita del turno, sceglie un mix
diversificato di esiti (uno per mercato, partite diverse) tra i best_bets
del modello. A fine partite valuta ogni esito, aggiorna il contatore
vinti/persi e archivia lo storico per giornata.

Le notifiche "pronostico indovinato" (foto) partono ESCLUSIVAMENTE dagli
esiti di questa schedina.
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
    out = []
    for fx in now_fx:
        preds = fx.predictions or {}
        for b in (preds.get("best_bets") or []):
            out.append({
                "fixture_id": fx.id, "home": fx.home, "away": fx.away,
                "start_ts": fx.start_ts,
                "market": b.get("market") or "1x2",
                "pick": b.get("pick"),
                "odds": b.get("odds"), "prob": b.get("prob") or 0,
                "edge": b.get("edge") or 0,
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
    picks = slip.get("picks") or []
    wins = sum(1 for p in picks if p.get("result") == "win")
    losses = sum(1 for p in picks if p.get("result") == "loss")
    return {
        "round": slip.get("round"), "created_at": slip.get("created_at"),
        "picks": picks, "wins": wins, "losses": losses,
    }


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

    # la finestra di 10 giorni di next_fixtures può spancciare due turni:
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
    """Valuta gli esiti pendenti usando i risultati in store (fallback:
    dettaglio evento via client)."""
    slip = store.get("schedina") or {}
    picks = slip.get("picks") or []
    scores = {}
    for rnd in (store.get("results") or []):
        for m in (rnd.get("matches") or []):
            hs, as_ = m.get("hs"), m.get("as")
            if hs is not None and as_ is not None:
                scores[m.get("id")] = (hs, as_)
    changed = False
    for p in picks:
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
                 slip.get("round"), p.get("home"), p.get("away"),
                 p.get("pick"), p.get("score"), p.get("result"))
    if changed:
        store.set("schedina", slip)
    return changed


# ------------------------------------------------------- notifiche foto
def pending_wins(store):
    """Esiti vinti della schedina non ancora notificati (foto)."""
    slip = store.get("schedina") or {}
    rnd = slip.get("round")
    out = []
    for p in slip.get("picks") or []:
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
    slip = store.get("schedina") or {}
    changed = False
    for p in slip.get("picks") or []:
        if f"sch-{slip.get('round')}-{p.get('fixture_id')}" in ids \
                and p.get("result") == "win":
            p["win_notified"] = True
            changed = True
    if changed:
        store.set("schedina", slip)


if __name__ == "__main__":
    # self-check: selezione diversificata + valutazione esito
    class _Store(dict):
        def __init__(self, data=None):
            super().__init__(data or {})
        def get(self, k, default=None):
            return super().get(k, default)
        def set(self, k, v):
            self[k] = v

    class _Fx:
        def __init__(self, fid, home, away, start_ts, bets):
            self.id, self.home, self.away = fid, home, away
            self.start_ts, self.round = start_ts, None
            self.predictions = {"best_bets": bets} if bets else {}

    now = time.time()
    fx = [
        _Fx("a", "A", "B", now + 1000, [{"market": "1x2", "pick": "1", "odds": 2.1, "prob": 0.7, "edge": 0.47}]),
        _Fx("b", "C", "D", now + 2000, [{"market": "1x2", "pick": "2", "odds": 2.3, "prob": 0.6, "edge": 0.38}]),
    ]
    st = _Store({"standings": [{"played": 3} for _ in range(10)]})
    slip = build(st, fx)
    assert slip["round"] == 4, slip
    assert len(slip["picks"]) == 2, slip
    # valutazione: 1-1 al match "a" azzecca il pareggio? pick è "1" -> perso.
    st.set("results", [{"round": 4, "matches": [
        {"id": "a", "hs": 1, "as": 1}]}])
    assert evaluate(st) is True
    assert slip["picks"][0]["result"] == "loss"
    # nuova settimana: la schedina precedente finisce nello storico
    fx2 = [_Fx("c", "E", "F", now + 8 * 86400, [{"market": "btts", "pick": "si", "odds": 1.9, "prob": 0.65, "edge": 0.23}])]
    st.set("standings", [{"played": 4} for _ in range(10)])
    slip2 = build(st, fx2)
    assert slip2["round"] == 5, slip2
    assert len(slip2["history"]) == 1, slip2
    assert slip2["history"][0]["round"] == 4
    print("schedina self-check OK")