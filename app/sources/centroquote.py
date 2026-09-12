"""Scraper best-effort del comparatore italiano (centroquote/oddsportal).

Nota: le quote sono caricate via JS/API; in moltissimi casi qui otteniamo
solo conferma del calendario. Se in futuro risulterà raggiungibile, il parser
JSON-LD qui sotto resta la base per le altre fonti.
"""
import json
import logging
import re

from bs4 import BeautifulSoup

import config
from app.core.http import HTTPClient

log = logging.getLogger("centroquote")


def _normalize(name):
    if not name:
        return ""
    import unicodedata
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()


class CentroquoteScraper:
    def __init__(self):
        self.http = HTTPClient(base=None, delay=1.0, host="centroquote")

    def fetch_matches(self):
        """Estrae dal JSON-LD l'elenco partite (home, away, data)."""
        raw = self.http.get(config.CENTROQUOTE_SERIEA_URL, as_json=False)
        if raw is None or raw.status_code != 200:
            log.info("centroquote non raggiungibile (HTTP %s)", getattr(raw, "status_code", None))
            return [], False
        html = raw.text
        doc = BeautifulSoup(html, "html.parser")
        matches = []
        for script in doc.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json.loads(script.string or "")
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            if data.get("@type") != "SportsEvent" and "name" not in data:
                continue
            name = data.get("name", "")
            if " - " not in name:
                continue
            home, away = [n.strip() for n in name.split(" - ", 1)]
            matches.append({
                "home": _normalize(home), "away": _normalize(away),
                "home_raw": home, "away_raw": away,
                "start": data.get("startDate"),
                "venue": "", "url": data.get("url", ""),
            })
        log.info("centroquote: %d partite trovate", len(matches))
        return matches, True


class SogosportScraper:
    def __init__(self):
        self.http = HTTPClient(base=None, delay=1.0, host="sogosport")

    def fetch_odds(self):
        raw = self.http.get(config.SOGOSPORT_SERIEA_URL, as_json=False)
        if raw is None or raw.status_code != 200:
            log.info("sogosport non raggiungibile -> skip quote")
            return [], False
        html = raw.text
        doc = BeautifulSoup(html, "html.parser")
        out = []
        for table in doc.find_all("table"):
            for row in table.find_all("tr"):
                cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                if len(cells) >= 4:
                    out.append(cells)
        return out, True


def sisal_snai_reachable():
    """Probe leggero: i bookmaker italiani sono spesso irraggiungibili
    da IP datacenter, ma funzionano su rete residenziale."""
    status = {}
    for name, url in (("sisal", config.SISAL_SERIEA_URL),
                      ("snai", config.SNAI_SERIEA_URL)):
        try:
            with HTTPClient(base=None, delay=0.0, host=name).session.get(
                    url, timeout=8, headers={"User-Agent": config.ASSETS_UA}) as r:
                status[name] = r.status_code == 200
        except Exception:
            status[name] = False
    return status