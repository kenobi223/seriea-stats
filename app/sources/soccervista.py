"""Fonte tipster: Soccervista (API JSON pubblica, senza chiave).

Il loro modello di previsione pubblica per ogni partita di Serie A:
  * predictionOutcome.outcome            -> esito 1X2 ("1"/"X"/"2")
  * predictionOutcome.goalsScoredPrediction -> "O"/"U" (Over/Under 2.5)
  * predictionOutcome.correctScorePrediction -> risultato esatto "0:1"
  * predictionOutcome.points             -> confidenza 1-10

L'endpoint /events/by/tournament/{templateId} restituisce `nextPredictions`
(imminenti) e `lastPredictions` (le ultime, con esito reale: servono per
misurare subito l'affidabilità della fonte, cioè "chi sbaglia va evitato").
"""
import logging
import re

import requests

import config

log = logging.getLogger("soccervista")

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": config.SV_API_ORIGIN + "/",
}

# alias: nome usato nei nostri fixture -> nomi come li scrive Soccervista
_ALIAS = {
    "ac milan": "milan",
    "acmilan": "milan",
    "as roma": "roma",
    "asroma": "roma",
    "ssc napoli": "napoli",
    "napoli ssc": "napoli",
    "internazionale": "inter",
    "inter milan": "inter",
    "bologna fc": "bologna",
    "bologna 1909": "bologna",
    "cfc genoa": "genoa",
    "genoa cfc": "genoa",
    "hellas verona": "verona",
    "hellasverona": "verona",
    "nazionale": "inter",
    "ss lazio": "lazio",
    "ssc napoli 1926": "napoli",
}


def _norm(name):
    if not name:
        return None
    name = _ALIAS.get(name.strip().lower(), name)
    name = re.sub(r"[\s\-_\.]+", "", name.lower())
    name = re.sub(r"(fc|cfc|ac|ssc|ss)\b", "", name)
    return name


def _match(text):
    per = text.find("%")
    out = None
    if per > 0:
        try:
            out = float(text[max(0, per - 4):per].rsplit(" ", 1)[-1].replace(",", "."))
        except ValueError:
            pass
    return out if out is not None else (float(text) if text.replace(".", "").isdigit() else None)


class SoccervistaClient:
    """Client per l'API interna di Soccervista."""

    def __init__(self, origin=config.SV_SERIE_A_PATH):
        self.path = origin
        self.http = requests.Session()
        self.http.headers.update(HEADERS)

    def fetch_serie_a(self, timeout=30, max_events=config.SV_MAX_DAYS):
        url = config.SV_API_ORIGIN + config.SV_SERIE_A_PATH
        r = self.http.get(url, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        return self._clean(data)

    def _clean(self, data):
        out = {"next": [], "last": [], "info": data.get("tournamentInfo") or {}}
        now_ts = __import__("time").time()
        horizon = now_ts + config.SV_MAX_DAYS * 86400
        for e in data.get("nextPredictions") or []:
            po = e.get("predictionOutcome") or {}
            if not po:
                continue
            ts = e.get("time") or 0
            if ts and (ts < now_ts - 3600 or ts > horizon):
                continue
            rec = self._event(e, po)
            if rec:
                out["next"].append(rec)
        for e in data.get("lastPredictions") or []:
            po = e.get("predictionOutcome") or {}
            if not po:
                continue
            rec = self._event(e, po)
            if rec:
                out["last"].append(rec)
        out["next"].sort(key=lambda x: x.get("ts") or 0)
        return out

    @staticmethod
    def _event(e, po):
        h = (e.get("homeParticipant") or {}).get("name")
        a = (e.get("awayParticipant") or {}).get("name")
        if not h or not a:
            return None
        fs = e.get("finalScore")
        res = None
        if fs and isinstance(fs, str) and ":" in fs:
            hs, as_ = fs.split(":", 1)
            try:
                res = {"home_score": int(hs), "away_score": int(as_)}
            except (TypeError, ValueError):
                res = None
        return {
            "id": e.get("id"),
            "home": h, "away": a,
            "ts": e.get("time") or 0,
            "outcome": po.get("outcome"),
            "goals": po.get("goalsScoredPrediction"),
            "score": po.get("correctScorePrediction"),
            "conf": po.get("points"),
            "final": res,
            "nm_h": _norm(h), "nm_a": _norm(a),
        }


def map_to_fixture(sv_events, fx):
    """Trova l'evento Soccervista corrispondente al fixture (per nome)."""
    nh = _norm(fx.home)
    na = _norm(fx.away)
    best = None
    for ev in sv_events:
        if ev["nm_h"] == nh and ev["nm_a"] == na:
            return ev
        if ev["nm_h"] == nh and (ev["nm_a"] == na or not na):
            best = ev  # match parziale solo sul lato casa (fallback)
    return best