"""Nuovo allenatore ("new-manager bounce").

Rilevamento ibrido:
  * manuale: `data/coaches.json` curato dall'utente (es. esonero noto, come
    la Fiorentina prima della trasferta di Venezia);
  * automatico: confronto il campo `manager` di Sofascore (`team/{id}`) con
    quanto già registrato; se cambia registro la data odierna come inizio
    della nuova era.

Formato registro (`data/coaches.json`), chiave = nome squadra come nei
fixtures:
    {"teams": {"Fiorentina": {"team_id": 2693, "manager": "...",
                              "since": <epoch>, "note": "...", "source": "manual"}}}

`since` = istante in cui il tecnico attuale ha preso la panchina; una squadra
con `since` recente (<= NEW_MANAGER_WINDOW_DAYS) è in "nuova era" e subisce
l'effetto bounce nel predictor e nel morale pre-partita.
"""
import logging
import time

import config
from app.core import kv

log = logging.getLogger("coach")


def load():
    """Legge il registro dal backend persistente (Redis se configurato,
    altrimenti `data/coaches.json`)."""
    data = kv.read_json("coaches.json")
    if isinstance(data, dict) and isinstance(data.get("teams"), dict):
        return data
    return {"teams": {}, "updated": 0}


def save(reg):
    kv.write_json("coaches.json", dict(reg, updated=int(time.time())))


def _manager_from_sofascore(client, team_id):
    """Nome del tecnico attuale da Sofascore (cached per `COACH_AUTO_TTL`)."""
    def _fetch():
        data = client.http.get(f"team/{team_id}")
        if not data:
            return None
        m = data.get("manager") or {}
        name = m.get("name") or m.get("fullName")
        if not name and isinstance(m, dict):
            nested = m.get("manager") or {}
            name = nested.get("name")
        return (name or "").strip() or None

    return client._ttl_cached(f"mgr-{team_id}", config.COACH_AUTO_TTL, _fetch)


def auto_update(reg, client, standings):
    """Aggiorna il registro confrontando i manager di Sofascore.

    - squadra già registrata: se il manager è cambiato e il cambio non è
      recentissimo, segna `since = oggi` come inizio nuova era;
    - primo contatto: registra il manager corrente senza `since` (non
      sappiamo quando è arrivato, quindi nessun bounce automatico).
    """
    teams = reg.setdefault("teams", {})
    changed = False
    for row in standings:
        tid = row.get("team_id")
        name = row.get("name")
        if not tid or not name:
            continue
        entry = teams.get(name)
        if entry is None:
            entry = {}
            teams[name] = entry
        auto = _manager_from_sofascore(client, tid)
        if not auto:
            continue
        known = entry.get("manager")
        if known and known != auto:
            since = entry.get("since")
            if since and time.time() - since < 7 * 86400:
                continue  # nuovo tecnico già registrato
            entry.update({
                "team_id": tid,
                "manager": auto,
                "last_manager": known,
                "since": int(time.time()),
                "source": "auto",
                "note": f"Nuovo allenatore rilevato: {auto} (sostituisce {known})",
            })
            changed = True
            log.info("coach: cambio allenatore automatico per %s -> %s",
                     name, auto)
        elif not known:
            entry.setdefault("team_id", tid)
            entry["manager"] = auto
            entry.setdefault("source", "sf")
            changed = True
    if changed:
        save(reg)
    return reg


def days_since(entry, now=None):
    since = entry.get("since") if isinstance(entry, dict) else None
    if not since:
        return None
    now = time.time() if now is None else now
    return (now - since) / 86400.0


def is_new(entry, now=None):
    if not config.NEW_MANAGER_ENABLED:
        return False
    d = days_since(entry, now)
    return d is not None and d <= config.NEW_MANAGER_WINDOW_DAYS


def info(entry, now=None):
    entry = entry or {}
    d = days_since(entry, now)
    return {
        "is_new": is_new(entry, now),
        "manager": entry.get("manager"),
        "since_days": round(d, 1) if d is not None else None,
        "note": entry.get("note"),
        "source": entry.get("source"),
    }


def attach(reg, fixtures, now=None):
    """Allega fx.coach = {"home": {...}, "away": {...}} a ogni fixture."""
    teams = reg.get("teams") or {}
    by_id = {e.get("team_id"): e for e in teams.values() if e.get("team_id")}
    for fx in fixtures:
        fx.coach = {
            "home": info(by_id.get(fx.home_id) or teams.get(fx.home), now),
            "away": info(by_id.get(fx.away_id) or teams.get(fx.away), now),
        }