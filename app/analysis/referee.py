"""Statistiche arbitri: media cartellini in carriera e in stagione."""
import logging
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("referee")


def _card_counts(incidents):
    y = r = 0
    for i in incidents:
        if i.get("type") == "card":
            case = str(i.get("class", "")).lower()
            if "red" in case:
                r += 1
            elif "yellow" in case:
                y += 1
    return y, r


def build_referee_stats(client, season_id, past_event_ids, workers=8):
    """Costruisce mappa arbitro -> statistiche di carriera + di stagione."""
    details = {}

    def fetch_detail(eid):
        return eid, client._cached(f"evd-{eid}", lambda: client.event_detail(eid))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for eid, det in pool.map(fetch_detail, past_event_ids):
            if det:
                details[eid] = det

    incident_map = client.incidents_for_events(list(details.keys()), workers=workers)

    registry = {}
    for eid, det in details.items():
        ref = det.get("referee") or {}
        ref_id = ref.get("id")
        if not ref_id:
            continue
        y, r = _card_counts(incident_map.get(eid, []))
        entry = registry.setdefault(ref_id, {
            "id": ref_id, "name": ref.get("name"),
            "career": {"games": ref.get("games"), "yellow": ref.get("yellow"),
                       "red": ref.get("red")},
            "season": [],
        })
        entry["season"].append({"y": y, "r": r, "eid": eid})

    out = {}
    for ref_id, entry in registry.items():
        career = entry["career"]
        games = career.get("games") or 0
        ypg = round((career.get("yellow") or 0) / games, 2) if games else None
        rpg = round((career.get("red") or 0) / games, 2) if games else None
        s = entry["season"]
        s_games = len(s)
        s_y = sum(x["y"] for x in s)
        s_r = sum(x["r"] for x in s)
        out[ref_id] = {
            "id": ref_id,
            "name": entry["name"],
            "career": career,
            "career_y_per_game": ypg,
            "career_r_per_game": rpg,
            "season_games": s_games,
            "season_y": s_y,
            "season_r": s_r,
            "season_y_per_game": round(s_y / s_games, 2) if s_games else None,
            "season_r_per_game": round(s_r / s_games, 2) if s_games else None,
        }
    log.info("arbitri mappati: %d", len(out))
    return out