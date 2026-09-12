"""Raccolta quote da tutte le fonti e merge con quelle manuali.

Storia quote: `fixture.history` è una lista di SNAPSHOT; ogni snapshot è a
sua volta una lista di OddsPick. Viene riaggiunto a ogni ciclo il valore
precedente, così `value.py` confronta l'ultimo snapshot con quello corrente
per rilevare movimenti di linea tra i refresh da 10 minuti.
"""
import logging
import unicodedata

from app.core import kv
from app.core.models import OddsPick

log = logging.getLogger("odds")

SNAPSHOTS_MAX = 24  # ~4 ore di storia a 10 min di intervallo


def load_manual_odds():
    """Quote inserite a mano (es. 'Lautaro tiro in porta @1.80 su Sisal')."""
    try:
        data = kv.read_json("manual_odds.json", default=[])
        return data if isinstance(data, list) else []
    except Exception as e:
        log.error("errore lettura quote manuali: %s", e)
        return []


def _norm(s):
    return unicodedata.normalize("NFKD", s or "").encode("ascii",
                                                         "ignore").decode().lower().strip()


def _match_key(home, away):
    return f"{_norm(home)}|{_norm(away)}"


def merge_odds(fixture, manual_entries=None):
    """Unisce le quote del fixture con quelle manuali per la stessa partita."""
    by_key = {}
    for o in fixture.odds:
        by_key[(o.source.lower(), o.market.lower(), o.pick.lower())] = o
    manual = manual_entries if manual_entries is not None else load_manual_odds()
    fkey = _match_key(fixture.home, fixture.away)
    for entry in manual:
        if _match_key(entry.get("home", ""), entry.get("away", "")) != fkey:
            continue
        o = OddsPick(source=entry.get("source", "manuale"),
                     market=entry.get("market", "varie"),
                     pick=entry.get("pick", entry.get("market", "?")),
                     odds=float(entry.get("odds", 0)))
        by_key[(o.source.lower(), o.market.lower(), o.pick.lower())] = o
    return sorted(by_key.values(), key=lambda x: (x.market, x.pick))


def tick(store, fixtures):
    """Da chiamare a ogni ciclo: salva lo snapshot precedente e aggiorna."""
    manual = load_manual_odds()
    for f in fixtures:
        prev = f.odds
        f.odds = merge_odds(f, manual)
        if prev:
            f.history.append(prev)
            f.history = f.history[-SNAPSHOTS_MAX:]
        else:
            f.history = []
    return manual