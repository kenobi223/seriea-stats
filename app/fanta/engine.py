"""Motore fanta: score giocatore, valutazione XI, formazione consigliata.

Classico fantacalcio base (moltiplicatori P3 / D2 / C1.5 / A1) + modifica
difesa. Lo score deriva dalle metriche REALI di fantacalcio.it: fantamedia
(FM, che include già bonus/malus) con fallback sulla media voto (MV),
corretto da titolarità (presenze) e agenda (forza della difesa avversaria).
"""
import logging

from app.fanta import players as fplayers
from app.fanta.store import MOD_SLOTS, MODULI

log = logging.getLogger("fanta.engine")

BASE_MULT = {"P": 3.0, "D": 2.0, "C": 1.5, "A": 1.0}
LABELS = ((7.0, "Solida 💪"), (6.2, "Discreta 👍"), (0.0, "Rischiosa ⚠️"))


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _label_for(score):
    for thr, lab in LABELS:
        if score >= thr:
            return lab
    return LABELS[-1][1]


def _next_opponent(store, team_name):
    """Prossima avversaria della squadra + posizione in classifica."""
    if not team_name:
        return None, None
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
    """Report valutativo del giocatore (score fanta + dettaglio trasparente)."""
    stats = fplayers.player_stats(p.get("id")) or {}
    mv = stats.get("mv")          # media voto
    fm = stats.get("fm")          # fantamedia (bonus/malus inclusi)
    pv = stats.get("pv") or 0     # presenze
    role = p.get("role") or stats.get("role") or "?"
    name = (stats.get("name") or p.get("name") or "")

    # valore base: fantamedia se disponibile, altrimenti media voto
    if fm:
        base = float(fm)
    elif mv:
        base = float(mv)
    else:
        base = 5.8                # mai sceso in campo: prudente
    base = _clamp(base, 4.5, 9.5)

    # titolarità: presenze (più partite = più affidabile)
    tit = None
    if pv:
        tit = _clamp(pv / 6.0, 0.2, 1.0)
        base = base * (0.9 + 0.1 * tit)
    else:
        base = base * 0.92        # nessuna presenza: sconto prudente

    # "bonusivo": fantamedia molto sopra la media voto
    bonusivo = bool(fm and mv and (fm - mv) > 0.5)

    # agenda: forza della difesa avversaria
    opp, opp_pos = _next_opponent(store, stats.get("team") or p.get("team"))
    agenda = ""
    if opp_pos:
        if opp_pos >= 14:
            base += 0.15
            agenda = f"vs {opp} (difesa debole)"
        elif opp_pos <= 5:
            base -= 0.15
            agenda = f"vs {opp} (difesa forte)"
        else:
            agenda = f"vs {opp}"

    # infortunio/squalifica (se l'utente li segnala)
    injured = any(name and (name.lower() in str(i).lower()
                            or str(i).lower() in name.lower())
                  for i in injured_names or ())
    if injured:
        base *= 0.15

    score = round(_clamp(base, 0.0, 9.8), 1)

    mod_note = ""
    if mod_dif and role == "D":
        score = round(min(9.8, score + 0.3), 1)
        mod_note = "mod difesa: +0.3"

    return {
        "id": p.get("id"), "name": p.get("name"), "team": p.get("team"),
        "role": role, "score": score, "mv": mv, "fm": fm,
        "tit": round((tit or 0) * 100) if tit is not None else None,
        "goals": stats.get("goals") or 0, "assists": stats.get("assists") or 0,
        "bonusivo": bonusivo, "trend": "up" if bonusivo else None,
        "agenda": agenda, "injured": injured, "mod_note": mod_note,
    }


def evaluate(store, user, xi_ids=None):
    """Valuta la formazione titolare (xi scelto o auto-best-XI)."""
    rosa = user.get("rosa") or []
    if not rosa:
        return {"error": "rosa vuota: aggiungi giocatori dal menu 🌹 Rosa"}
    modulo = user.get("modulo") or "4-4-2"
    mod_dif = bool(user.get("mod_dif"))
    slots = MOD_SLOTS.get(modulo) or MOD_SLOTS["4-4-2"]

    reports = {p["id"]: player_report(store, p, mod_dif) for p in rosa}

    xi_ids = list(xi_ids or user.get("xi") or [])
    if not xi_ids:
        best = best_xi(reports.values(), modulo)
        xi_ids = [r["id"] for r in best["xi"]]
    else:
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
    total = _weighted(xi)
    return {
        "modulo": modulo, "mod_dif": mod_dif,
        "xi": xi, "total": round(total, 2),
        "label": _label_for(total),
        "auto": not bool(user.get("xi")),
    }


def _weighted(xi):
    num = 0.0
    den = 0.0
    for r in xi:
        mult = BASE_MULT.get(r["role"], 1.0)
        num += mult * r["score"]
        den += mult
    return (num / den) if den else 0.0


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
    total = _weighted(xi)
    return {"xi": xi, "total": round(total, 2), "feasible": feasible}


def suggest(store, user, mod_dif=False):
    """Formazione consigliata: prova tutti i moduli, scegli il totale più alto."""
    rosa = user.get("rosa") or []
    if not rosa:
        return {"error": "rosa vuota"}
    reports = [player_report(store, p, mod_dif) for p in rosa]
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