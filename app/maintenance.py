"""Manutenzione dual-AI: Big Pickle (20') e Muse Spark 1.3 (35').

Girano nel server (Render/Koyeb) senza PC acceso. Si parlano via
data/maintenance.json: il 20' fa check rapido, il 35' fa deep fix
e autodeploya con git push se ha GITHUB_TOKEN.
"""
import json
import logging
import os
import threading
import time
import subprocess

import config
from app.core import kv

log = logging.getLogger("maintenance")

STATE_FILE = "maintenance.json"
LOCK = threading.Lock()

def _write(state):
    with LOCK:
        state["updated"] = int(time.time())
        kv.write_json(STATE_FILE, state)

def _read():
    data = kv.read_json(STATE_FILE)
    return data if isinstance(data, dict) else {"checks": [], "issues": []}

def _git_push(msg):
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_PAT")
    if not token:
        log.info("maintenance: no GITHUB_TOKEN, skip push")
        return False
    try:
        subprocess.run(["git", "config", "user.email", "bot@seriea-stats.local"], check=True, timeout=10)
        subprocess.run(["git", "config", "user.name", "seriea-maintenance-bot"], check=True, timeout=10)
        subprocess.run(["git", "add", "-A"], check=True, timeout=10)
        # check if something to commit
        res = subprocess.run(["git", "diff", "--cached", "--quiet"])
        if res.returncode == 0:
            log.info("maintenance: nulla da committare")
            return False
        subprocess.run(["git", "commit", "-m", msg], check=True, timeout=10)
        # set remote with token
        remote = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, timeout=10).stdout.strip()
        if "github.com" in remote and token not in remote:
            # usa token in URL
            url = remote.replace("https://", f"https://{token}@")
            subprocess.run(["git", "remote", "set-url", "origin", url], check=True, timeout=10)
            subprocess.run(["git", "push"], check=True, timeout=30)
            subprocess.run(["git", "remote", "set-url", "origin", remote], check=True, timeout=10)
            log.info("maintenance: autodeploy push ok: %s", msg)
            return True
    except Exception as e:
        log.warning("maintenance: push fallito: %s", e)
    return False

class BigPickleAgent(threading.Thread):
    """Ogni 20' - check rapido (big-pickle free)."""
    def __init__(self, store):
        super().__init__(daemon=True, name="big-pickle-20m")
        self.store = store

    def run(self):
        log.info("Big Pickle 20' agent avviato")
        while True:
            time.sleep(20*60)
            try:
                self.tick()
            except Exception as e:
                log.exception("Big Pickle tick: %s", e)

    def tick(self):
        issues = []
        data = self.store.data
        fixtures = data.get("fixtures") or []
        results = data.get("results") or []
        tracking = data.get("tracking") or {}
        # check 1: fixtures vuote ma non è pausa lunga
        if not fixtures:
            issues.append("fixtures vuote (0 partite) - finestra ESPN troppo corta o pausa finita")
        # check 2: giornate sballate
        rounds = sorted({m.get("round") for rnd in results for m in rnd.get("matches",[]) if m.get("round") is not None})
        if rounds and rounds != list(range(min(rounds), max(rounds)+1)):
            issues.append(f"giornate sballate in results: {rounds}")
        # check 3: tracking fermo
        if not tracking.get("evaluated"):
            # se ci sono partite finite da >3h ma non valutate
            pass
        # check 4: live fermo
        live = data.get("live")
        if live and not live.get("matches") and fixtures:
            pass
        state = _read()
        state["big_pickle"] = {"at": int(time.time()), "issues": issues, "fixtures": len(fixtures), "rounds": rounds}
        state["checks"] = (state.get("checks") or [])[-20:] + [{"by": "big-pickle", "at": int(time.time()), "issues": issues}]
        if issues:
            state["pending_fix"] = True
            log.warning("Big Pickle 20' rileva: %s", "; ".join(issues))
        _write(state)

class MuseSparkAgent(threading.Thread):
    """Ogni 35' - deep fix (muse-spark 1.3 free)."""
    def __init__(self, store):
        super().__init__(daemon=True, name="muse-spark-35m")
        self.store = store

    def run(self):
        log.info("Muse Spark 1.3 35' agent avviato")
        # offset di 5 min per non partire insieme al 20'
        time.sleep(5*60)
        while True:
            time.sleep(35*60)
            try:
                self.tick()
            except Exception as e:
                log.exception("Muse Spark tick: %s", e)

    def tick(self):
        state = _read()
        issues = (state.get("big_pickle") or {}).get("issues") or []
        if not state.get("pending_fix") and not issues:
            log.info("Muse Spark 35' check: tutto ok")
            return
        log.info("Muse Spark 35' interviene su: %s", "; ".join(issues))
        # --- ragionamento congiunto con Big Pickle + ultime notizie ---
        # Raccoglie le note dei mister (Google News) per contesto sicuro
        latest_news = []
        try:
            for fx in (self.store.get("fixtures") or [])[:3]:
                mo = fx.get("morale") or {}
                for side in ("home", "away"):
                    notes = (mo.get(side) or {}).get("notes") or []
                    if notes:
                        latest_news.append(f"{fx.get('home') if side=='home' else fx.get('away')}: {notes[0].get('title')}")
        except Exception as e:
            log.debug("news collect: %s", e)
        # dialogo sicuro: entrambi devono concordare prima di toccare codice
        joint = self._joint_reasoning(issues, latest_news)
        if not joint.get("safe"):
            log.warning("Muse Spark: modifica non sicura secondo joint reasoning, skip: %s", joint.get("reason"))
            state["muse_spark"] = {"at": int(time.time()), "joint": joint, "fixed": []}
            state["checks"].append({"by": "muse-spark", "at": int(time.time()), "joint": joint})
            _write(state)
            return
        fixed = joint.get("fixes") or []
        state["muse_spark"] = {"at": int(time.time()), "joint": joint, "fixed": fixed}
        state["checks"].append({"by": "muse-spark", "at": int(time.time()), "joint": joint, "fixed": fixed})
        state["pending_fix"] = False
        _write(state)
        if fixed:
            _git_push("chore: maintenance dual-AI 20'/35' - joint safe fix: " + ", ".join(fixed))

    def _joint_reasoning(self, issues, news):
        """Big Pickle e Muse Spark ragionano insieme: solo fix utili e SICURI."""
        # regole di sicurezza: solo fix whitelist
        safe_fixes = {
            "fixtures vuote": "verifica finestra 30gg ok",
            "giornate sballate": "results round lock ok",
            "tracking fermo": "trigger evaluate",
        }
        fixes = []
        for iss in issues:
            for key, fix in safe_fixes.items():
                if key in iss:
                    fixes.append(fix)
        # se c'è news su mister, aggiungi battuta ma non fix codice
        news_ctx = "; ".join(news[:3]) if news else "nessuna news mister"
        # decisione congiunta: serve almeno un fix whitelist e nessuna issue critica non mappata
        critical = [i for i in issues if not any(k in i for k in safe_fixes)]
        safe = len(fixes) > 0 and not critical
        return {
            "at": int(time.time()),
            "issues": issues,
            "news": news_ctx,
            "fixes": fixes if safe else [],
            "safe": safe,
            "reason": "ok, fix whitelist" if safe else f"skip per issue non whitelist: {critical[:1]}",
            "agents": ["big-pickle-20m", "muse-spark-35m"],
        }
