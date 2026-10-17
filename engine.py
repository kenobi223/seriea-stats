"""Motore standalone per GitHub Actions: un singolo run_cycle + lock.

Niente Flask, niente thread Telegram, niente tunnel: solo raccolta dati,
pronostici, schedina e apprendimento (learning.json), con persistenza su
Redis (Upstash) se REDIS_URL e' impostato.

Uso:
  python engine.py

Exit code:
  0  ciclo completato (o lock occupato: un altro run e' in corso)
  1  abort (stagione/classifica non disponibili) o errore imprevisto

Lock anti-overlap su Redis (seriea:engine:lock, TTL 20 min): protegge da
cron sovrapposti o run manuali paralleli. Senza Redis (locale) si esegue
senza lock, come prima.
"""
import os
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Default ambientali per il runner headless (devono precedere import config):
# - solo ESPN (Sofascore e' bloccato dagli IP datacenter, ogni chiamata
#   resterebbe in retry Tor e il ciclo non chiuderebbe)
# - niente proxy Tor (non esiste su GitHub Actions)
os.environ.setdefault("SOFASCORE_TOR_MODE", "never")
os.environ.setdefault("DATA_SOURCE_ORDER", "espn")

import config  # noqa: E402
from app.core import kv  # noqa: E402
from app.core.store import Store  # noqa: E402
from app.scheduler import run_cycle  # noqa: E402

LOCK_KEY = "seriea:engine:lock"
LOCK_TTL = 1200          # 20 min > ciclo tipico (2-5 min), < 2x cron 15'


def _acquire_lock():
    """Prova a prendere il lock Redis. Restituisce l'owner id o None."""
    r = kv._redis()
    if r is None:
        return "no-redis"          # locale: niente lock, come prima
    owner = uuid.uuid4().hex[:12]
    try:
        ok = r.set(LOCK_KEY, owner, nx=True, ex=LOCK_TTL)
        if ok:
            return owner
        return None
    except Exception as e:
        # Redis raggiungibile ma errore sul comando: procedi senza lock
        # (peggio bloccare il motore per un errore Redis transitorio)
        print(f"lock non disponibile ({e}): procedo senza lock", flush=True)
        return "lock-error"


def _release_lock(owner):
    if owner in ("no-redis", "lock-error"):
        return
    r = kv._redis()
    if r is None:
        return
    try:
        cur = r.get(LOCK_KEY)
        if isinstance(cur, bytes):
            cur = cur.decode()
        if cur == owner:
            r.delete(LOCK_KEY)
    except Exception as e:
        print(f"release lock fallita ({e}): scade da sola tra {LOCK_TTL}s",
              flush=True)


def main():
    t0 = time.time()
    owner = _acquire_lock()
    if owner is None:
        print("SKIP: un altro run del motore e' in corso (lock occupato)",
              flush=True)
        return 0
    try:
        # REDIS_URL presente ma Redis non va: meglio fallire in faccia
        # che "riuscire" scrivendo su disco effimero che si perde alla
        # fine del job (stato/learning non esisterebbero per sito e bot).
        if config.REDIS_URL and kv._redis() is None:
            print("ENGINE_FAIL: REDIS_URL impostato ma Upstash/Redis non "
                  "raggiungibile (controlla scheme rediss:// + user default "
                  "+ token) -> abortisco senza scrivere su disco",
                  flush=True)
            return 1

        store = Store()
        store.load()
        store.set("code", "actions-engine@github")
        store.save()

        run_cycle(store)

        # meta del motore dentro state.json: il Worker lo espone in /api/health
        state = store.load() or store.data
        slip = state.get("schedina") or {}
        picks = slip.get("picks") or []
        meta = {
            "last_run_ts": int(time.time()),
            "last_run_ok": True,
            "last_run_secs": round(time.time() - t0, 1),
            "host": "github-actions",
        }
        store.set("engine", meta)
        store.save()
        print("ENGINE_OK " + str({
            "secs": meta["last_run_secs"],
            "standings": len(state.get("standings") or []),
            "fixtures": len(state.get("fixtures") or []),
            "results_rounds": len(state.get("results") or []),
            "schedina_round": slip.get("round"),
            "schedina_picks": len(picks),
            "schedina_wins": sum(1 for p in picks if p.get("result") == "win"),
            "schedina_losses": sum(1 for p in picks if p.get("result") == "loss"),
            "updated": state.get("updated"),
        }), flush=True)
        return 0
    except Exception as e:
        print(f"ENGINE_FAIL: {e}", flush=True)
        try:
            store.set("engine", {"last_run_ts": int(time.time()),
                                 "last_run_ok": False,
                                 "last_run_error": str(e)[:200]})
            store.save()
        except Exception:
            pass
        return 1
    finally:
        _release_lock(owner)


if __name__ == "__main__":
    sys.exit(main())
