"""Schedina community: gli utenti (web o Telegram) compilano i propri esiti.

- Un invio per persona a giornata: chiave `ip:<ip>` sul web,
  `tg:<chat_id>` sul bot. Chiavi diverse = persone diverse.
- Per partita UN solo esito scelto tra i tre mercati:
  1X2 (1/x/2), Over/Under 2.5 (over_2.5/under_2.5), BTTS (si/no).
- Valutazione vs risultati con lo stesso criterio della schedina modello
  (app.core.markets.match_outcomes).
- Stato persistito in `community.json` (kv), raggruppato per giornata.
"""
import logging
import time

from app.core import kv, markets
from app.analysis import schedina

log = logging.getLogger("community")

VALID = {
    "1x2": {"1", "x", "2"},
    "over_under": {"over_2.5", "under_2.5"},
    "btts": {"si", "no"},
}
MAX_ROUNDS = 4            # giornate di archivio in cima a quelle correnti


def load():
    data = kv.read_json("community.json")
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("rounds"), dict):
        data["rounds"] = {}
    return data


def save(data):
    kv.write_json("community.json", data)


def current_round(store):
    return schedina.current_round(store)


def _round_fixtures(store, rnd):
    """Fixture della giornata come dict per id (stringa)."""
    out = {}
    for f in store.get("fixtures") or []:
        if str(f.get("round")) == str(rnd) and f.get("id") is not None:
            out[str(f["id"])] = f
    return out


def validate(store, rnd, picks):
    """Valida i pick della giornata. Restituisce (picks_normalizzati, errore)."""
    fixtures = _round_fixtures(store, rnd)
    if not fixtures:
        return None, "nessuna partita per questa giornata"
    valid, seen = [], set()
    for p in picks or []:
        fid = str(p.get("fixture_id") or "")
        mkt = p.get("market")
        pk = p.get("pick")
        if fid not in fixtures:
            return None, f"partita non valida: {fid}"
        if fid in seen:
            return None, "più di un esito per la stessa partita"
        if mkt not in VALID or pk not in VALID[mkt]:
            return None, "mercato o esito non valido"
        seen.add(fid)
        fx = fixtures[fid]
        valid.append({
            "fixture_id": fid, "home": fx.get("home"), "away": fx.get("away"),
            "market": mkt, "pick": pk, "result": None, "score": None,
        })
    if not valid:
        return None, "nessun esito scelto"
    return valid, None


def submit(store, key, picks, meta=None, rnd=None):
    """Registra la schedina di una persona. Status: ok | already | errore."""
    cur = current_round(store)
    if cur is None:
        return "giornata non disponibile", None
    if rnd is None:
        rnd = cur
    elif str(rnd) != str(cur):
        return "giornata non aggiornata: ricarica e riprova", None
    valid, err = validate(store, rnd, picks)
    if err:
        return err, None
    data = load()
    block = data["rounds"].setdefault(str(rnd), {})
    if not isinstance(block.get("entries"), dict):
        block["entries"] = {}
    if key in block["entries"]:
        return "already", block["entries"][key]
    entry = {"picks": valid, "ts": int(time.time())}
    entry.update({k: v for k, v in (meta or {}).items() if v is not None})
    block["entries"][key] = entry
    _prune(data)
    save(data)
    log.info("community giornata %s: nuovo invio %s (%d esiti)",
             rnd, key, len(valid))
    return "ok", entry


def entry_for(store, key, rnd=None):
    if key is None:
        return None, None
    rnd = rnd if rnd is not None else current_round(store)
    if rnd is None:
        return None, None
    block = load()["rounds"].get(str(rnd)) or {}
    entry = (block.get("entries") or {}).get(key)
    return rnd, entry


def snapshot(store, key=None):
    """Stato della giornata corrente per API/sezione bot."""
    rnd = current_round(store)
    data = load()
    if rnd is None:
        return {"round": None, "participants": 0, "fixtures": [],
                "aggregates": {}, "my": None}
    block = data["rounds"].get(str(rnd)) or {}
    entries = block.get("entries") or {}
    fixtures = sorted(_round_fixtures(store, rnd).values(),
                      key=lambda f: f.get("start_ts") or 0)
    agg = {}
    for e in entries.values():
        for p in e.get("picks") or []:
            m = agg.setdefault(str(p.get("fixture_id")), {})
            per_m = m.setdefault(p.get("market"), {})
            per_m[p.get("pick")] = per_m.get(p.get("pick"), 0) + 1
    my = entries.get(key) if key else None
    return {
        "round": rnd,
        "participants": len(entries),
        "fixtures": [{"id": str(f.get("id")), "home": f.get("home"),
                      "away": f.get("away"),
                      "start_ts": f.get("start_ts")} for f in fixtures],
        "aggregates": agg,
        "my": my,
    }


def top_pick(agg_fixture):
    """Esito più scelto di una partita: ((mercato, esito), n)."""
    best = None
    for mkt, picks in (agg_fixture or {}).items():
        for pk, n in picks.items():
            if best is None or n > best[1]:
                best = ((mkt, pk), n)
    return best


def evaluate(store):
    """Valuta tutti i pick pendenti contro i risultati (idempotente)."""
    data = load()
    rounds = data.get("rounds") or {}
    scores = {}
    for rnd in store.get("results") or []:
        for mm in rnd.get("matches") or []:
            hs, as_ = mm.get("hs"), mm.get("as")
            if hs is not None and as_ is not None and mm.get("id") is not None:
                scores[str(mm["id"])] = (hs, as_)
    changed = False
    for _rkey, block in rounds.items():
        for entry in (block.get("entries") or {}).values():
            for p in entry.get("picks") or []:
                if p.get("result"):
                    continue
                s = scores.get(str(p.get("fixture_id")))
                if not s:
                    continue
                actual = markets.match_outcomes(s[0], s[1])
                p["score"] = f"{s[0]}-{s[1]}"
                p["result"] = "win" if actual.get(p.get("market")) == p.get("pick") \
                    else "loss"
                changed = True
                log.info("community: %s %s vs %s -> %s",
                         p.get("home"), p.get("away"),
                         p.get("pick"), p.get("result"))
    if _prune(data):
        changed = True
    if changed:
        save(data)
    return changed


def _prune(data):
    rounds = data.get("rounds") or {}
    if len(rounds) <= MAX_ROUNDS:
        return False
    try:
        keep = sorted(rounds, key=lambda k: int(k), reverse=True)[:MAX_ROUNDS]
    except (TypeError, ValueError):
        return False
    for k in list(rounds):
        if k not in keep:
            del rounds[k]
    return True


def entry_counts(entry):
    """(vinti, persi, pending) di una schedina inviata."""
    picks = (entry or {}).get("picks") or []
    return (sum(1 for p in picks if p.get("result") == "win"),
            sum(1 for p in picks if p.get("result") == "loss"),
            sum(1 for p in picks if not p.get("result")))
