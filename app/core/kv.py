"""Persistenza JSON: locale (disco) o remota (Redis) con fallback automatico.

Se ``config.REDIS_URL`` è impostato (es. Upstash Redis free), i file importanti
(state/learning/follows/langs/started/manual_odds) vengono salvati in Redis:
sopravvivono così al filesystem effimero di Render free. Senza REDIS_URL il
comportamento resta identico a prima (file JSON su disco).
"""
import json
import logging
import os
import threading
import time

import config

log = logging.getLogger("kv")

_lock = threading.RLock()
_client = None
_tried = False
_tried_at = 0

# nome logico degli "stati" -> percorso locale di fallback
KEYS = {
    "state.json": config.STATE_FILE,
    "learning.json": config.LEARNING_FILE,
    "follows.json": config.FOLLOWS_FILE,
    "started.json": config.STARTED_FILE,
    "manual_odds.json": config.MANUAL_ODDS_FILE,
    "subs.json": config.SUBS_FILE,
    "tipsters.json": config.TIPSTERS_FILE,
    "market_alpha.json": config.MARKET_ALPHA_FILE,
    "ou_alert.json": config.OU_ALERT_FILE,
    "tg_offset.json": os.path.join(config.DATA_DIR, "tg_offset.json"),
    "coaches.json": config.COACHES_FILE,
}


def _redis_url():
    """Normalizza REDIS_URL: Upstash richiede TLS (rediss), accettiamo anche
    la URL `redis://...` che Upstash mostra nella console."""
    url = config.REDIS_URL or ""
    if url.startswith("redis://") and "upstash.io" in url:
        return url.replace("redis://", "rediss://", 1)
    return url


def _redis():
    global _client, _tried, _tried_at
    if not config.REDIS_URL:
        return None
    # retry ogni 5 minuti se prima fallito
    if _client is None and _tried and (time.time() - _tried_at) < 300:
        return None
    if _client is None and _tried and (time.time() - _tried_at) >= 300:
        _tried = False
    with _lock:
        if _client is None and not _tried:
            _tried = True
            _tried_at = time.time()
        else:
            return _client
        try:
            import redis
            _client = redis.from_url(
                _redis_url(), socket_timeout=5, socket_connect_timeout=5,
                retry_on_timeout=True)
            _client.ping()
            log.info("persistenza remota Redis attiva (%s)", config.REDIS_URL.split("@")[-1])
        except Exception as e:
            log.warning("Redis non raggiungibile (%s): uso disco", e)
            _client = None
    return _client


def read_json(name, default=None):
    """Legge un blocco JSON dal backend primario (Redis) o dal disco."""
    r = _redis()
    raw = None
    if r is not None:
        try:
            raw = r.get("seriea:" + name)
        except Exception as e:
            log.warning("kv read redis %s: %s", name, e)
        if raw is not None:
            try:
                return json.loads(raw)
            except Exception:
                pass
        # Redis raggiungibile ma chiave assente: semina il file locale se esiste
        local = _read_local(name)
        if local is not None:
            try:
                r.set("seriea:" + name, json.dumps(local, ensure_ascii=False))
                log.info("kv: seminato %s da disco a Redis", name)
            except Exception as e:
                log.warning("kv seed %s: %s", name, e)
            return local
    return _read_local(name, default)


def write_json(name, data):
    """Scrive un blocco JSON: Redis se disponibile, altrimenti disco."""
    r = _redis()
    if r is not None:
        try:
            r.set("seriea:" + name, json.dumps(data, ensure_ascii=False))
            return
        except Exception as e:
            log.warning("kv write redis %s: %s (rollback su disco)", name, e)
    _write_local(name, data)


def exists_local(name):
    path = KEYS.get(name)
    return path is not None and os.path.exists(path)


def _read_local(name, default=None):
    path = KEYS.get(name)
    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.error("errore lettura %s: %s", name, e)
    return default


def _write_local(name, data):
    path = KEYS.get(name)
    if not path:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)