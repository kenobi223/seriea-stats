"""Motore fanta: score giocatore, valutazione XI, formazione consigliata.

Classico fantacalcio base (moltiplicatori P3 / D2 / C1.5 / A1) + modifica
difesa ON (nota difesa rialzata, nessun calcolo reale pre-partita: è una
preferenza di lega, la applico solo come peso leggero sui difensori).
Lo score fanta deriva dal voto Sofascore (0-10): rating → voto fanta,
corretto da titolarità (minuti/presenze), andamento recente, gol/assist
e agenda (forza difesa avversaria).
"""
import logging

from app.fanta import players as fplayers
from app.fanta.store import MOD_SLOTS, MODULI

log = logging.getLogger("fanta.engine")

BASE_MULT = {"P": 3.0, "D": 2.0, "C": 1.5, "A": 1.0}
LABELS = ((7.5, "Solida 💪"), (6.5, "Discreta 👍"), (0.0, "Rischiosa ⚠️"))


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _label_for(score):
    for thr, lab in LABELS:
        if score >= thr:
            return lab
    return LABELS[-1][1]


def _next_opponent(store, team_name):
    """Prossima avversaria della squadra del giocatore + posizione in classifica."""
    if not team_name:
        return None, None
    now = (store.get("updated") or 0)
    best = None
    for f in store.get("fixtures") or []:
        if f.get("home") == team_name:
            opp, opp_id = f.get("away"), f.get("away_id")
        elif f.get("away") == team_name:
            opp, opp_id = f.get("home"), f.get("home_id")
        else:
            continue
        ts = f.get("start_ts") or 0
        if ts and (best is None or ts < best[0]):
            best = (ts, opp, opp_id)
    if not best:
        return None, None
    pos = None
    for row in store.get("standings") or []:
        if row.get("name") == best[1] or str(row.get("team_id")) == str(best[2]):
            pos = row.get("position")
            break
    return best[1], pos


def player_report(store, p, mod_dif=False, injured_names=()):
    """Report valutativo di un giocatore della rosa.

    Restituisce dict con score fanta (0-10) + dettaglio trasparente.
    """
    stats = fplayers.player_stats(p.get("id")) or {}
    rating = stats.get("avg_rating")
    apps = stats.get("appearances")
    minutes = stats.get("minutes")
    goals = stats.get("goals") or 0
    assists = stats.get("assists") or 0
    name = (stats.get("name") or p.get("name") or "").lower()

    # voto fanta base: rating sofascore → scala 5.5-9.5
    if rating:
        score = 5.5 + (float(rating) - 6.0) * 1.6
    else:
        # nessun voto recente: basati su gol/presenze (fallback prudente)
        gpm = (goals / apps) if apps else 0
        score = 5.8 + _clamp(gpm * 6.0, 0, 1.5)
    score = _clamp(score, 5.0, 9.5)

    # titolarità: minuti medi per presenza
    tit = None
    if apps and minutes:
        mins_per_app = minutes / apps
        tit = _clamp(mins_per_app / 90.0, 0.35, 1.0)
        if apps < 3:
            tit *= 0.85
        score *= 0.85 + 0.15 * tit

    # andamento
    trend = stats.get("trend")
    if trend == "up":
        score += 0.25
    elif trend == "down":
        score -= 0.25

    # gol / assist
    role = p.get("role") or stats.get("position") or "?"
    score += _clamp(goals * 0.12, 0, 1.0) if role in ("A", "C") else \
        _clamp(goals * 0.08, 0, 0.6)
    score += _clamp(assists * 0.06, 0, 0.4)

    # agenda: difesa avversaria
    opp, opp_pos = _next_opponent(store, stats.get("team") or p.get("team"))
    agenda = ""
    if opp_pos:
        if opp_pos >= 14:
            score += 0.15
            agenda = f"vs {opp} (difesa debole)"
        elif opp_pos <= 5:
            score -= 0.15
            agenda = f"vs {opp} (difesa forte)"
        else:
            agenda = f"vs {opp}"

    # infortunio/squalifica
    injured = any(name and (name in str(i).lower() or str(i).lower() in name)
                  for i in injured_names or ())
    if injured:
        score *= 0.15
    score = round(_clamp(score, 0.0, 9.8), 1)

    # mod difesa: leggero rilancio sui difensori (preferenza di lega)
    mod_note = ""
    if mod_dif and role == "D":
        score = round(min(9.8, score + 0.3), 1)
        mod_note = "mod difesa: +0.3"

    return {
        "id": p.get("id"), "name": p.get("name"), "team": p.get("team"),
        "role": role, "score": score, "rating": rating,
        "tit": round((tit or 0) * 100) if tit is not None else None,
        "goals": goals, "assists": assists, "trend": trend,
        "agenda": agenda, "injured": injured, "mod_note": mod_note,
    }


def _injured_names(store, team_name):
    if not team_name:
        return ()
    try:
        cl = fplayers._client()
        team_id = None
        for row in store.get("standings") or []:
            if row.get("name") == team_name:
                team_id = row.get("team_id")
                break
        if not team_id:
            return ()
        return tuple(i.get("player") for i in (cl.team_injuries(team_id) or [])
                     if i.get("player"))
    except Exception as e:
        log.debug("fanta: team_injuries(%s): %s", team_name, e)
        return ()


def evaluate(store, user, xi_ids=None):
    """Valuta la formazione titolare (xi scelto o auto-best-XI)."""
    rosa = user.get("rosa") or []
    if not rosa:
        return {"error": "rosa vuota: aggiungi giocatori dal menu 🌹 Rosa"}
    modulo = user.get("modulo") or "4-4-2"
    mod_dif = bool(user.get("mod_dif"))
    slots = MOD_SLOTS.get(modulo) or MOD_SLOTS["4-4-2"]

    reports = {}
    inj_cache = {}
    for p in rosa:
        team = p.get("team")
        if team not in inj_cache:
            inj_cache[team] = _injured_names(store, team)
        reports[p["id"]] = player_report(store, p, mod_dif, inj_cache[team])

    xi_ids = list(xi_ids or user.get("xi") or [])
    if not xi_ids:
        best = best_xi(reports.values(), modulo)
        xi_ids = [r["id"] for r in best["xi"]]
    else:
        # validazione: esattamente 1 P + slots da modulo, tutti in rosa
        by_id = {p["id"]: p for p in rosa}
        roles = []
        ok = True
        for pid in xi_ids:
            p = by_id.get(pid)
            if not p:
                ok = False
                break
            roles.append(p.get("role") or "?")
        if ok:
            for role, n in slots.items():
                if roles.count(role) != n:
                    ok = False
                    break
        if not ok:
            best = best_xi(reports.values(), modulo)
            xi_ids = [r["id"] for r in best["xi"]]

    xi = [reports[pid] for pid in xi_ids if pid in reports]
    xi.sort(key=lambda r: (-BASE_MULT.get(r["role"], 1), -r["score"]))
    total = _weighted(xi, mod_dif)
    return {
        "modulo": modulo, "mod_dif": mod_dif,
        "xi": xi, "total": round(total, 2),
        "label": _label_for(total),
        "auto": not bool(user.get("xi")),
    }


def _weighted(xi, mod_dif):
    num = 0.0
    den = 0.0
    for r in xi:
        mult = BASE_MULT.get(r["role"], 1.0)
        num += mult * r["score"]
        den += mult
    if not den:
        return 0.0
    return num / den


def best_xi(reports, modulo):
    """Migliore XI disponibile per il modulo (score desc per ruolo)."""
    slots = MOD_SLOTS.get(modulo) or MOD_SLOTS["4-4-2"]
    by_role = {}
    for r in reports:
        by_role.setdefault(r.get("role") or "?", []).append(r)
    xi = []
    feasible = True
    for role, n in slots.items():
        pool = sorted(by_role.get(role, []), key=lambda r: -r["score"])
        if len(pool) < n:
            feasible = False
            xi.extend(pool)
        else:
            xi.extend(pool[:n])
    total = _weighted(xi, False)
    return {"xi": xi, "total": round(total, 2), "feasible": feasible}


def suggest(store, user, mod_dif=False):
    """Formazione consigliata: prova tutti i moduli, scegli il totale più alto."""
    rosa = user.get("rosa") or []
    if not rosa:
        return {"error": "rosa vuota"}
    inj_cache = {}
    reports = []
    for p in rosa:
        team = p.get("team")
        if team not in inj_cache:
            inj_cache[team] = _injured_names(store, team)
        reports.append(player_report(store, p, mod_dif, inj_cache[team]))
    best = None
    for mod in MODULI:
        res = best_xi(reports, mod)
        if not res["feasible"]:
            continue
        if best is None or res["total"] > best["total"]:
            best = {"modulo": mod, **res}
    if not best:
        return {"error": "rosa insufficiente per qualsiasi modulo "
                         "(servono almeno 1P+3D+3C+2A)"}
    best["mod_dif"] = mod_dif
    best["label"] = _label_for(best["total"])
    return best
