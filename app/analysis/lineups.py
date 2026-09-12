"""Probabili formazioni "merge di fonti".

Unisce due predittori indipendenti per il XI più probabile:
  1. Sofascore (`probable_xi`) — reale, disponibile a ridosso del fischio;
  2. predittore interno — pesa gli ultimi undici ufficiali (titolarità +
     minuti), esclude gli infortunati/squalificati e riassembla l'undici
     per reparto. Sempre disponibile, quindi copre anche le partite a
     5-7 giorni quando la fonte esterna non pubblica ancora nulla.
Quando entrambe le fonti esistono, i giocatori concordi sono marcati
`src=both`, quelli solo Sofascore `sf`, quelli solo del modello `model`,
e i posti in contesa vengono segnalati in `contese`.
"""
import logging
import config

log = logging.getLogger("lineups")

_POS = ("G", "D", "M", "F")
_POS_BASE = {"G": 1, "D": 4, "M": 3, "F": 3}


def official_lineups(client, team_id, season_id, k=config.FORM_WINDOW):
    """Ultimi k undici ufficiali della squadra nella stagione (cached)."""
    events = client.team_events(team_id, max_events=50)
    fin = sorted((e for e in events
                  if e.get("finished") and e.get("season_id") == season_id
                  and e.get("home_id") is not None),
                 key=lambda e: e.get("start_ts") or 0, reverse=True)[:k]
    out = []
    for e in fin:
        side = "home" if e["home_id"] == team_id else "away"
        lu = client._cached(f"lu-{e['id']}",
                            lambda eid=e["id"]: client.lineups(eid))
        if not lu or not lu.get(side):
            continue
        out.append(lu[side])
    return out


def _loop_weight(st):
    return (st["starts"], st["minutes"])


def model_xi(client, team_id, season_id, missing_ids=(), inj_names=()):
    """Predizione interna: undici + formazione dagli ultimi ufficiali."""
    lus = official_lineups(client, team_id, season_id)
    stats = {}
    formation = None
    for blk in lus:
        if not formation and blk.get("formation"):
            formation = blk["formation"]
        for p in blk.get("players", []) or []:
            if p.get("substitute"):
                continue
            pid, name = p.get("id"), p.get("name")
            if pid is None or not name:
                continue
            pos = p.get("position") if p.get("position") in _POS else "F"
            st = stats.setdefault(pid, {"id": pid, "name": name,
                                        "position": pos,
                                        "shirt": p.get("shirt"),
                                        "starts": 0, "minutes": 0})
            st["starts"] += 1
            st["minutes"] += p.get("minutes") or 0
    if not stats:
        return None

    miss = {m for m in (missing_ids or ()) if m is not None}
    inj = [str(n).lower() for n in (inj_names or ()) if n]
    kept = []
    for st in stats.values():
        if st["id"] in miss:
            continue
        nl = st["name"].lower()
        if any(n in nl or nl in n for n in inj):
            continue
        kept.append(st)
    kept.sort(key=_loop_weight, reverse=True)

    groups = {"G": [], "D": [], "M": [], "F": []}
    for s in kept:
        groups[s["position"]].append(s)

    picks = []
    for pos in _POS:
        for s in groups[pos][:_POS_BASE[pos]]:
            picks.append(s)
    taken = {p["id"] for p in picks}
    rest = [s for s in kept if s["id"] not in taken]
    for s in rest[: 11 - len(picks)]:
        picks.append(s)

    n_matches = max(1, len(lus))
    for s in picks:
        s["conf"] = round(100 * s["starts"] / n_matches)
    picks.sort(key=lambda s: _POS.index(s["position"]))
    return {"formation": formation or "4-3-3",
            "players": picks, "window": len(lus)}


def _pick(p):
    return {"id": p["id"], "name": p["name"], "position": p.get("position"),
            "shirt": p.get("shirt")}


def merge(sf, model):
    """Fonde Sofascore e modello in un unico XI probabile (max 11)."""
    if not model or not model.get("players"):
        return sf
    if not sf or not sf.get("players"):
        pl = []
        for mp in model["players"]:
            ep = _pick(mp)
            ep.update(src="model", conf=mp.get("conf"))
            pl.append(ep)
        return {"confirmed": False, "formation": model["formation"],
                "players": pl, "_source": "model"}

    mset = {p["id"]: p for p in model["players"]}
    out = []
    for p in sf["players"]:
        ep = dict(p)
        mp = mset.get(p.get("id"))
        if mp:
            ep["src"] = "both"
            ep["conf"] = 100
        else:
            ep["src"] = "sf"
            ep["conf"] = None
        out.append(ep)

    taken = {p.get("id") for p in out}
    contese = []
    for mp in model["players"]:
        if mp["id"] in taken:
            continue
        if len(out) >= 11:
            contese.append(mp["name"])
            continue
        ep = _pick(mp)
        ep.update(src="model", conf=mp.get("conf"))
        out.append(ep)
    return {"confirmed": False,
            "formation": sf.get("formation") or model["formation"],
            "players": out, "_source": "merge", "contese": contese[:6]}


def compute_fixture_xis(client, fx, season_id):
    """Garantisce un XI probabile per entrambe le squadre della partita."""
    for side in ("home", "away"):
        pxi = fx.probable_xi or {}
        sf = pxi.get(side)
        form = fx.form_home if side == "home" else fx.form_away
        missing = [p.get("id") for p in ((sf or {}).get("missing") or [])]
        inj_names = [i.get("player") or "" for i in (form or {}).get("injuries", [])]
        tid = fx.home_id if side == "home" else fx.away_id
        model = model_xi(client, tid, season_id, missing, inj_names)
        merged = merge(sf, model)
        if merged:
            pxi[side] = merged
            fx.probable_xi = pxi