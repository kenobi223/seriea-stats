"""DB giocatori Serie A da fantacalcio.it (fonte ufficiale, dati fanta reali).

Una sola richiesta alla pagina statistiche fornisce per ogni calciatore:
nome, ruolo classico (P/D/C/A), squadra, presenze (PV), media voto (MV),
fantamedia (FM), gol, assist, ammonizioni, espulsioni. Niente Tor, niente
API a pagamento: la pagina risponde in diretto.

L'indice è cachato in kv `fanta_index.json` (TTL 6h). Le statistiche sono
dentro l'indice stesso (nessuna chiamata per giocatore).
"""
import logging
import re
import threading
import time

import requests

from app.core import kv

log = logging.getLogger("fanta.players")

STATS_URL = "https://www.fantacalcio.it/statistiche-serie-a"

INDEX_KEY = "fanta_index.json"
STATUS_KEY = "fanta_index_status.json"
INDEX_TTL = 6 * 3600

_build_lock = threading.Lock()
_building = False
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/120.0 Safari/537.36"}

ROLE_MAP = {"p": "P", "d": "D", "c": "C", "a": "A"}


def _fnum(value):
    """'7,0' -> 7.0 ; '' -> None."""
    if value is None:
        return None
    s = str(value).strip().replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _team_from_slug(slug):
    if not slug:
        return "?"
    return slug.replace("-", " ").strip().title()


def _set_status(**fields):
    try:
        st = kv.read_json(STATUS_KEY)
        st = st if isinstance(st, dict) else {}
        st.update(fields)
        kv.write_json(STATUS_KEY, st)
    except Exception as e:
        log.debug("fanta status write: %s", e)


def index_status():
    st = kv.read_json(STATUS_KEY)
    return st if isinstance(st, dict) else {}


def _fetch_html(url):
    r = requests.get(url, headers=_UA, timeout=25)
    r.raise_for_status()
    return r.text


def _parse(html):
    """Estrae i giocatori dalla pagina statistiche fantacalcio.it."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    players = []
    for tr in soup.find_all("tr", class_="player-row"):
        try:
            a = tr.find("a", class_="player-link")
            if a is None:
                continue
            name_tag = a.find("span")
            name = (name_tag or a).get_text(strip=True)
            if not name:
                continue
            href = a.get("href") or ""
            m = re.search(r"/squadre/([^/]+)/[^/]+/(\d+)", href)
            team_slug = m.group(1) if m else ""
            pid = int(m.group(2)) if m else None
            th = tr.find("th", class_="player-role-classic")
            role_val = ""
            if th is not None:
                span = th.find("span", class_="role")
                role_val = (span.get("data-value") if span else "") or ""
            role = ROLE_MAP.get(str(role_val).lower(), "?")
            team_cell = tr.find("td", class_="player-team")
            team_abbr = team_cell.get_text(strip=True) if team_cell else ""

            def cell(cls):
                td = tr.find("td", class_=cls)
                return td.get_text(strip=True) if td else ""

            players.append({
                "id": pid if pid is not None else f"{name}-{team_abbr}",
                "name": name,
                "role": role,
                "team": _team_from_slug(team_slug),
                "team_abbr": team_abbr,
                "pv": _int(cell("player-match-playeds")),
                "mv": _fnum(cell("player-grade-avg")),
                "fm": _fnum(cell("player-fanta-grade-avg")),
                "goals": _int(cell("player-scoreds")),
                "assists": _int(cell("player-assists")),
                "yellows": _int(cell("player-yellows")),
                "reds": _int(cell("player-reds")),
            })
        except Exception as e:
            log.debug("fanta parse row: %s", e)
    return players


def build_index(store=None):
    """Indice giocatori (una richiesta). Cached 6h in kv."""
    cached = kv.read_json(INDEX_KEY)
    if isinstance(cached, dict) and cached.get("players") and \
            time.time() - (cached.get("t") or 0) < INDEX_TTL:
        return cached["players"]
    try:
        html = _fetch_html(STATS_URL)
        players = _parse(html)
    except Exception as e:
        log.warning("fanta: fetch fantacalcio.it fallita: %s", e)
        _set_status(last_error=str(e)[:120], last_ts=int(time.time()))
        return cached.get("players") if isinstance(cached, dict) else []
    now = int(time.time())
    if players:
        kv.write_json(INDEX_KEY, {"t": now, "players": players})
        log.info("fanta: indice fantacalcio.it (%d giocatori)", len(players))
    _set_status(last_ts=now, players=len(players), building=False,
                source="fantacalcio.it")
    return players


def _build_safe():
    global _building
    try:
        build_index()
    except Exception as e:
        log.warning("fanta: build in background fallita: %s", e)
    finally:
        with _build_lock:
            _building = False


def ensure_index_async(store=None):
    """Ritorna l'indice (cache) e, se assente, lo costruisce in background
    (una singola richiesta veloce, quindi di fatto quasi sincrono)."""
    global _building
    cached = kv.read_json(INDEX_KEY)
    players = cached.get("players") if isinstance(cached, dict) else None
    fresh = players and time.time() - (cached.get("t") or 0) < INDEX_TTL
    if fresh:
        return players
    with _build_lock:
        if not _building:
            _building = True
            _set_status(building=True)
            threading.Thread(target=_build_safe, daemon=True,
                             name="fanta-index").start()
    return players or []


def search(store, query, limit=15):
    """Ricerca locale per nome (o squadra). Prefisso > sottostringa > token."""
    q = str(query or "").strip().lower()
    if not q:
        return []
    players = ensure_index_async(store)
    tokens = [t for t in q.split() if t]
    scored = []
    for p in players:
        name = (p.get("name") or "").lower()
        team = (p.get("team") or "").lower()
        score = 0
        if name.startswith(q) or team.startswith(q):
            score = 3
        elif q in name or q in team:
            score = 2
        elif tokens and all(t in name for t in tokens):
            score = 1
        if score:
            scored.append((score, len(name), p))
    scored.sort(key=lambda x: (-x[0], x[1], x[2].get("name") or ""))
    return [p for _, _, p in scored[:limit]]


def get_by_id(pid):
    """Statistiche del giocatore dall'indice (nessuna rete)."""
    cached = kv.read_json(INDEX_KEY)
    players = cached.get("players") if isinstance(cached, dict) else []
    for p in players or []:
        if p.get("id") == pid:
            return p
    return None


# compatibilità col vecchio engine (Sofascore): le stats sono nell'indice
def player_stats(pid):
    return get_by_id(pid) or {"id": pid}


def enrich(player):
    """Nella nuova fonte ruolo/squadra sono già nell'indice: no-op."""
    return player