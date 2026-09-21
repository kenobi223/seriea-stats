"""Scraping dati Serie A via Firecrawl.

Free tier: funziona senza API key (rate-limited per IP).
Per limiti più alti, impostare FIRECRAWL_API_KEY.
"""
import logging
import os

log = logging.getLogger("firecrawl_scraper")

_client = None


def _get_client():
    global _client
    if _client is None:
        try:
            from firecrawl import Firecrawl
            api_key = os.environ.get("FIRECRAWL_API_KEY")
            if api_key:
                _client = Firecrawl(api_key=api_key)
            else:
                _client = Firecrawl()
            log.info("Firecrawl client inizializzato (key: %s)",
                     "sì" if api_key else "no (free tier)")
        except ImportError:
            log.warning("firecrawl-py non installato")
            return None
    return _client


def scrape_url(url, params=None):
    """Scrape singola URL. Restituisce markdown del contenuto."""
    client = _get_client()
    if not client:
        return None
    try:
        result = client.scrape(url, params=params or {})
        return result
    except Exception as e:
        log.warning("Firecrawl scrape %s: %s", url, e)
        return None


def crawl_site(url, limit=10, params=None):
    """Crawl di un sito. Restituisce lista di pagine."""
    client = _get_client()
    if not client:
        return []
    try:
        result = client.crawl(url, limit=limit, params=params or {})
        return result
    except Exception as e:
        log.warning("Firecrawl crawl %s: %s", url, e)
        return []


def search_web(query, params=None):
    """Cerca sul web. Restituisce risultati."""
    client = _get_client()
    if not client:
        return []
    try:
        result = client.search(query, params=params or {})
        return result
    except Exception as e:
        log.warning("Firecrawl search: %s", e)
        return []
