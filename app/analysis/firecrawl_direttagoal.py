"""Scraping Serie A da DirettaGoal via Firecrawl.

DirettaGoal non ha API pubbliche → Firecrawl scrape + parse.
Free tier senza key (rate-limited per IP).
"""
import json
import logging
import re

log = logging.getLogger("firecrawl_direttagoal")

_BASE = "https://www.direttagoal.it"
_SERIE_A = _BASE + "/calcio/serie-a"


def _fc():
    from app.analysis.firecrawl_scraper import _get_client
    return _get_client()


def scrape_classifica():
    """Scrape classifica Serie A da DirettaGoal."""
    client = _fc()
    if not client:
        return None
    try:
        result = client.scrape(_SERIE_A + "/classifica")
        md = result.get("markdown", "") if isinstance(result, dict) else str(result)
        return _parse_classifica(md)
    except Exception as e:
        log.warning("scrape classifica: %s", e)
        return None


def scrape_risultati():
    """Scrape risultati/fixture da DirettaGoal."""
    client = _fc()
    if not client:
        return []
    try:
        result = client.scrape(_SERIE_A)
        md = result.get("markdown", "") if isinstance(result, dict) else str(result)
        return _parse_risultati(md)
    except Exception as e:
        log.warning("scrape risultati: %s", e)
        return []


def scrape_partita(url):
    """Scrape dettaglio singola partita (formazioni, stats, incidenti)."""
    client = _fc()
    if not client:
        return None
    try:
        full_url = url if url.startswith("http") else _BASE + url
        result = client.scrape(full_url)
        md = result.get("markdown", "") if isinstance(result, dict) else str(result)
        return _parse_partita(md)
    except Exception as e:
        log.warning("scrape partita %s: %s", url, e)
        return None


def _parse_classifica(md):
    """Parse classifica dal markdown."""
    rows = []
    lines = md.splitlines()
    for line in lines:
        # cerca pattern: "1. TeamName  Pts  W D L ..."
        m = re.match(
            r'(\d+)[.\s]+(.+?)\s+(\d+)\s+(\d+)-(\d+)-(\d+)', line
        )
        if m:
            rows.append({
                "pos": int(m.group(1)),
                "team": m.group(2).strip(),
                "pts": int(m.group(3)),
                "w": int(m.group(4)),
                "d": int(m.group(5)),
                "l": int(m.group(6)),
            })
    return rows if rows else None


def _parse_risultati(md):
    """Parse risultati/fixture dal markdown."""
    matches = []
    lines = md.splitlines()
    for i, line in enumerate(lines):
        # cerca pattern: "HomeTeam 1 - 2 AwayTeam" o "HomeTeam - AwayTeam"
        m = re.search(r'(\w[\w\s]+?)\s+(\d+)\s*[-–]\s*(\d+)\s+(\w[\w\s]+)', line)
        if m:
            matches.append({
                "home": m.group(1).strip(),
                "away": m.group(4).strip(),
                "home_goals": int(m.group(2)),
                "away_goals": int(m.group(3)),
            })
    return matches


def _parse_partita(md):
    """Parse dettaglio partita dal markdown."""
    data = {"raw_length": len(md)}
    lines = md.splitlines()
    for i, line in enumerate(lines):
        low = line.lower()
        if "formazion" in low:
            data["lineups_section"] = "\n".join(lines[i:i+20])
        if "statistic" in low:
            data["stats_section"] = "\n".join(lines[i:i+15])
        if "cartellini" in low or "incidenti" in low:
            data["incidents_section"] = "\n".join(lines[i:i+15])
    return data
