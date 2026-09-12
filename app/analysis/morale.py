"""Morale pre/post partita + conferenze dei mister (Google News RSS).

* pre_morale: 1-10 dai dati (punti a gara recenti, infortuni, forza
  avversario); il punteggio vero arriva dalle parole del mister.
* press_notes: ultimi titoli delle conferenze stampa del club via
  Google News RSS (cached su disco 6h), per leggere il tono dello spogliatoio.
* post_morale: delta morale dopo il risultato (vittoria/sconfitta, scarto,
  gol segnati, porta inviolata) per il resoconto post-partita.
"""
import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote

import config

log = logging.getLogger("morale")

PRESS_CACHE = os.path.join(config.DATA_DIR, "cache", "press")
PRESS_TTL = 6 * 3600
PRESS_MAX = 3


def _label(score):
    if score >= 9:
        return "ottimo"
    if score >= 7.5:
        return "buono"
    if score >= 6:
        return "tiepidi"
    if score >= 4:
        return "sotto-pressione"
    return "crisi"


def _ppg(form):
    entries = (form or {}).get("last_results") or []
    n = len(entries) or 1
    pts = sum(3 if r.get("result") == "H" else
              (1 if r.get("result") == "D" else 0) for r in entries)
    return pts / n


def pre_morale(form, injuries=0, opp_pts=None, new_coach=False):
    """Morale pre-partita 1-10 (dati) prima delle conferenze."""
    ppg = _ppg(form)
    score = 5.0 + ppg * 1.6
    score -= min(injuries, 4) * 0.5
    if opp_pts is not None:
        if opp_pts <= 2:
            score += 0.6
        elif opp_pts >= 6:
            score -= 0.6
    if new_coach:
        score += config.NEW_MANAGER_MORALE_BONUS
    score = round(min(10, max(1, score)), 1)
    return {"score": score, "label": _label(score), "ppg": round(ppg, 2)}


def post_morale(home_score, away_score, side_home=True):
    """Delta morale (e descrizione) dopo il risultato finale."""
    mine = home_score if side_home else away_score
    theirs = away_score if side_home else home_score
    if mine > theirs:
        delta = 2
    elif mine == theirs:
        delta = 0
    else:
        delta = -2
    diff = mine - theirs
    if diff >= 3:
        delta += 1
    elif diff <= -3:
        delta -= 1
    if mine >= 3:
        delta += 0.5
    if theirs == 0:
        delta += 0.5
    delta = round(min(3, max(-3, delta)), 1)
    if delta >= 2:
        desc = "vola: vittoria convincente"
    elif delta > 0:
        desc = "su, fiducia ritrovata"
    elif delta == 0:
        desc = "stabile"
    elif delta > -2:
        desc = "giù, fallimento"
    else:
        desc = "crisi: sconfitta pesante"
    return delta, desc


def _load_press(team_key):
    path = os.path.join(PRESS_CACHE, team_key + ".json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if time.time() - data.get("t", 0) < PRESS_TTL:
            return data.get("notes") or []
    except Exception as e:
        log.debug("press cache %s: %s", team_key, e)
    return None


def _save_press(team_key, notes):
    os.makedirs(PRESS_CACHE, exist_ok=True)
    path = os.path.join(PRESS_CACHE, team_key + ".json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"t": time.time(), "notes": notes}, f, ensure_ascii=False)
    except Exception as e:
        log.debug("press save %s: %s", team_key, e)


def _norm(name):
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def press_notes(client, team_name):
    """Ultime 2-3 conferenze stampa del club (titoli + sorgente)."""
    team_key = _norm(team_name) or "n"
    cached = _load_press(team_key)
    if cached is not None:
        return cached
    q = quote(f'"{team_name}" conferenza stampa mister')
    url = ("https://news.google.com/rss/search?q=" + q +
           "&hl=it&gl=IT&ceid=IT:it")
    notes = []
    try:
        resp = client.http.get(url, as_json=False, timeout=20,
                               retries=1)
        if resp is not None and resp.status_code == 200:
            root = ET.fromstring(resp.text)
            for it in root.iter("item"):
                title_el = it.find("title")
                if title_el is None or not title_el.text:
                    continue
                notes.append({
                    "title": title_el.text.strip(),
                    "link": (it.findtext("link") or "").strip(),
                })
                if len(notes) >= PRESS_MAX:
                    break
    except Exception as e:
        log.debug("press %s fallita: %s", team_name, e)
    _save_press(team_key, notes)
    return notes