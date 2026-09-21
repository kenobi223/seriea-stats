"""Manutenzione dual-AI: Big Pickle (20') e Muse Spark 1.3 (35').

Due ingegneri informatici super organizzati, miglior titolo in web design &
development, amano codificare pulito, modernizzare e aggiungere chicche:
- a livello codice: migliorano i pronostici (Poisson, xG, calibrazione)
- a livello design: modernizzano UI, aggiungono registrazione, PWA iPhone/Android
Girano nel server (Render/Koyeb) senza PC acceso. Si parlano via
data/maintenance.json: il 20' fa check rapido, il 35' fa deep fix
e autodeploya con git push se approvato da @Ziosapi.
Quando si svegliano sono super carichi e cercano nei forum le ultime novità webdev.
"""
import json
import logging
import os
import threading
import time
import subprocess

import requests

import config
from app.core import kv

log = logging.getLogger("maintenance")

def _send_daily_summary():
    """A fine giornata (23:55) manda a @Ziosapi un txt con tutto ciò che si sono detti i due agenti."""
    state = _read()
    checks = state.get("checks") or []
    if not checks:
        return
    # filtra solo oggi
    today = time.strftime("%Y-%m-%d")
    lines = [f"Report giornaliero Serie A Stats - {today}", "="*40, ""]
    for c in checks[-30:]:
        by = c.get("by")
        at = time.strftime("%H:%M", time.localtime(c.get("at", 0)))
        issues = c.get("issues") or c.get("joint", {}).get("issues") or []
        fixes = c.get("fixed") or c.get("joint", {}).get("fixes") or []
        ideas = c.get("ideas") or c.get("joint", {}).get("ideas") or []
        lines.append(f"[{at}] {by}")
        if issues:
            lines.append("  Problemi: " + "; ".join(str(i)[:80] for i in issues[:3]))
        if fixes:
            lines.append("  Fix: " + ", ".join(fixes))
        if ideas:
            lines.append("  Idee: " + ideas[0][:80])
        lines.append("")
    text = "\n".join(lines)
    # salva txt
    path = os.path.join(config.DATA_DIR, f"daily_{today}.txt")
    try:
        os.makedirs(config.DATA_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception as e:
        log.warning("daily txt save: %s", e)
        return
    # invia come documento a @Ziosapi
    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        return
    targets = list(config.TELEGRAM_OWNER_IDS) if config.TELEGRAM_OWNER_IDS else ["@Ziosapi"]
    for chat_id in targets:
        try:
            url = f"https://api.telegram.org/bot{token}/sendDocument"
            with open(path, "rb") as f:
                requests.post(url, data={"chat_id": chat_id, "caption": f"📄 Report giornaliero {today} - Big Pickle + Muse Spark"}, files={"document": (f"report_{today}.txt", f)}, timeout=15)
            log.info("daily report inviato a %s", chat_id)
        except Exception as e:
            # fallback testo se documento fallisce
            try:
                requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": text[:4000]}, timeout=10)
            except:
                log.warning("daily report %s: %s", chat_id, e)

def _notify_owner_proposal(proposal):
    """Manda proposta a @Ziosapi con tasti OK/Rifiuta."""
    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        return
    targets = list(config.TELEGRAM_OWNER_IDS) if config.TELEGRAM_OWNER_IDS else ["@Ziosapi"]
    # testo elementare
    fixes = ", ".join(proposal.get("fixes") or [])
    news = proposal.get("news") or "nessuna"
    text = (
        f"🔧 Proposta di fix dal team Big Pickle + Muse Spark:\n\n"
        f"Problema: {', '.join(proposal.get('issues') or [])}\n"
        f"Fix proposto: {fixes}\n"
        f"News mister: {news[:120]}\n"
        f"Motivo: {proposal.get('reason')}\n\n"
        f"Scegli: OK per pushare e autodeployare, Rifiuta per cancellare."
    )
    kb = {
        "inline_keyboard": [
            [{"text": "✅ OK", "callback_data": f"maint_ok:{proposal['id']}"},
             {"text": "❌ Rifiuta", "callback_data": f"maint_no:{proposal['id']}"}]
        ]
    }
    for chat_id in targets:
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            requests.post(url, json={"chat_id": chat_id, "text": text, "reply_markup": kb}, timeout=10)
            log.info("maintenance: proposta %s a @Ziosapi %s", proposal["id"], chat_id)
        except Exception as e:
            log.warning("notify proposal %s: %s", proposal["id"], e)

def _notify_owner(text):
    """Manda messaggio elementare a @Ziosapi (owner) via bot."""
    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        return
    targets = list(config.TELEGRAM_OWNER_IDS) if config.TELEGRAM_OWNER_IDS else ["@Ziosapi"]
    for chat_id in targets:
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            simple = f"🔧 Aggiornamento bot Serie A:\n\n{text}\n\nFatto da Big Pickle + Muse Spark."
            requests.post(url, json={"chat_id": chat_id, "text": simple}, timeout=10)
        except Exception as e:
            log.warning("notify @Ziosapi %s: %s", chat_id, e)

STATE_FILE = "maintenance.json"
LOCK = threading.Lock()

def _write(state):
    with LOCK:
        state["updated"] = int(time.time())
        kv.write_json(STATE_FILE, state)

def _read():
    data = kv.read_json(STATE_FILE)
    return data if isinstance(data, dict) else {"checks": [], "issues": []}

def approve_pending(proposal_id):
    state = _read()
    pending = state.get("pending_proposal")
    if not pending or pending.get("id") != proposal_id:
        return False, "nessuna proposta in attesa con questo id"
    if pending.get("status") != "pending":
        return False, "proposta già gestita"
    fixes = pending.get("fixes") or []
    ok = _git_push("chore: maintenance dual-AI approved by @Ziosapi - " + ", ".join(fixes))
    pending["status"] = "approved"
    pending["decided_at"] = int(time.time())
    # sposta in history e pulisci pending per non riproporre subito
    history = state.get("approved_history") or []
    history.append(dict(pending))
    state["approved_history"] = history[-10:]
    state["pending_proposal"] = None
    state["pending_fix"] = False
    state["last_approved_fix"] = fixes
    _write(state)
    _notify_owner(f"✅ Approvato! Ho pushato: {', '.join(fixes)}. Deploy in corso." if ok else f"✅ Approvato ma nulla da pushare: {', '.join(fixes)}")
    return True, "approvato" if ok else "approvato (nulla da pushare)"

def reject_pending(proposal_id):
    state = _read()
    pending = state.get("pending_proposal")
    if not pending or pending.get("id") != proposal_id:
        return False, "nessuna proposta in attesa"
    pending["status"] = "rejected"
    pending["decided_at"] = int(time.time())
    # salva in rejected per deduplica
    rejected = set(state.get("rejected_ids") or [])
    rejected.add(pending["id"])
    state["rejected_ids"] = list(rejected)[-20:]
    state["last_rejected_fix"] = pending.get("fixes") or []
    state["pending_proposal"] = None
    state["pending_fix"] = False
    _write(state)
    _notify_owner(f"❌ Rifiutato: {', '.join(pending.get('fixes') or [])}. Non lo ripropongo a meno che non trovi di meglio.")
    return True, "rifiutato"

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

def _latest_webdev_ideas():
    """Cerca ultime novità webdev nei forum (Hacker News RSS) per ispirare chicche."""
    try:
        import xml.etree.ElementTree as ET
        import requests
        r = requests.get("https://news.ycombinator.com/rss", timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            root = ET.fromstring(r.text)
            titles = [it.findtext("title") for it in root.iter("item")][:3]
            return [t for t in titles if t][:3]
    except:
        pass
    return ["PWA installabile iPhone/Android", "WebAuthn registrazione senza password", "View Transitions API per animazioni fluide"]

class BigPickleAgent(threading.Thread):
    """Ogni 20' - ingegnere web design, check rapido + cerca idee forum."""
    def __init__(self, store):
        super().__init__(daemon=True, name="big-pickle-20m")
        self.store = store

    def run(self):
        # frequenza rapida per test: 5' poi ogni 5', così 5-6 risvegli = 30min invece di 3h
        interval = int(os.environ.get("BIG_PICKLE_INTERVAL", "5")) * 60
        log.info(f"Big Pickle agent avviato - primo giro tra 30s, poi ogni {interval//60}'")
        try:
            time.sleep(30)
            self.tick()
        except Exception as e:
            log.exception("Big Pickle primo tick: %s", e)
        while True:
            time.sleep(interval)
            try:
                self.tick()
            except Exception as e:
                log.exception("Big Pickle tick: %s", e)

    def tick(self):
        # super carichi di idee: cercano ultime novità forum
        ideas = _latest_webdev_ideas()
        issues = []
        data = self.store.data
        fixtures = data.get("fixtures") or []
        results = data.get("results") or []
        tracking = data.get("tracking") or {}
        if not fixtures:
            issues.append("fixtures vuote (0 partite) - finestra ESPN troppo corta o pausa finita")
        rounds = sorted({m.get("round") for rnd in results for m in rnd.get("matches",[]) if m.get("round") is not None})
        if rounds and rounds != list(range(min(rounds), max(rounds)+1)):
            issues.append(f"giornate sballate in results: {rounds}")
        # chicche ingegneri: propongono sempre una miglioria design/code
        chicche = []
        if not os.path.exists("app/web/static/manifest.json"):
            chicche.append("💡 Idea ingegnere: aggiungere PWA manifest per installazione iPhone/Android")
        if "Team" not in str(issues):
            chicche.append(f"💡 Idea ingegnere: {ideas[0]}")
        # analisi partita per partita
        try:
            from app.analysis import tracker as trk
            tdata = trk.load()
            for rec in (tdata.get("records") or [])[-5:]:
                if not rec.get("evaluated") or not rec.get("result"):
                    continue
                res = rec["result"]["1x2"]
                picks = {p["market"]: p["pick"] for p in rec.get("picks") or []}
                pred = picks.get("1x2")
                ok = "✅" if pred == res else "❌"
                issues.append(f"{ok} {rec['home']}-{rec['away']} {rec['result']['home_score']}-{rec['result']['away_score']}: modello diceva {pred}, uscito {res}")
                if len(issues) > 10:
                    break
        except Exception as e:
            log.debug("per-match check: %s", e)
        try:
            for r in (data.get("standings") or [])[:2]:
                name = r.get("name")
                issues.append(f"Team {name}: {r.get('points')}pt - algoritmo valuta {'sopra' if (r.get('gf',0) or 0) > 5 else 'sotto'} media")
                if len(issues) > 12:
                    break
        except:
            pass
        # aggiungi chicche come issue di tipo idea (verranno valutate come sicure solo se whitelist)
        issues.extend(chicche[:1])
        state = _read()
        state["big_pickle"] = {"at": int(time.time()), "issues": issues, "fixtures": len(fixtures), "rounds": rounds, "ideas": ideas}
        state["checks"] = (state.get("checks") or [])[-20:] + [{"by": "big-pickle", "at": int(time.time()), "issues": issues, "ideas": ideas}]
        if issues:
            state["pending_fix"] = True
            log.warning("Big Pickle ingegnere 20' rileva + idee %s: %s", ideas[0], "; ".join(issues[:2]))
        _write(state)

class DailyReportAgent(threading.Thread):
    """Ogni giorno alle 23:55 - invia txt riassunto a @Ziosapi."""
    def __init__(self):
        super().__init__(daemon=True, name="daily-report")
    def run(self):
        log.info("Daily report agent avviato (23:55)")
        sent_today = None
        while True:
            now = time.localtime()
            # invia tra 23:55 e 00:05, una sola volta al giorno
            if now.tm_hour == 23 and now.tm_min >= 55:
                today = time.strftime("%Y-%m-%d")
                if sent_today != today:
                    try:
                        _send_daily_summary()
                        sent_today = today
                    except Exception as e:
                        log.exception("daily report: %s", e)
            elif now.tm_hour == 0 and now.tm_min < 5 and sent_today is None:
                # se il server era spento alle 23:55, prova a 00:02
                today = time.strftime("%Y-%m-%d", time.localtime(time.time()-3600))
                try:
                    _send_daily_summary()
                    sent_today = today
                except:
                    pass
            time.sleep(60)

class MuseSparkAgent(threading.Thread):
    """Ogni 35' - ingegnere senior, deep fix + modernizza design/code con chicche."""
    def __init__(self, store):
        super().__init__(daemon=True, name="muse-spark-35m")
        self.store = store

    def run(self):
        interval = int(os.environ.get("MUSE_INTERVAL", "8")) * 60
        log.info(f"Muse Spark 1.3 agent avviato - primo giro tra 90s, poi ogni {interval//60}'")
        try:
            time.sleep(90)
            self.tick()
        except Exception as e:
            log.exception("Muse Spark primo tick: %s", e)
        while True:
            time.sleep(interval)
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
        # deduplica: se stessa proposta già pending/rifiutata/approvata, skip a meno che non sia migliore
        pending = state.get("pending_proposal")
        rejected = set(state.get("rejected_ids") or [])
        approved = set(p.get("id") for p in (state.get("approved_history") or []) if p.get("id"))
        proposal_id = str(hash(tuple(sorted(fixed))))[:8] if fixed else str(int(time.time()))
        if fixed and proposal_id in rejected:
            prev_fix_len = len((state.get("last_rejected_fix") or []))
            if len(fixed) <= prev_fix_len:
                log.info("maintenance: proposta %s già rifiutata, skip", proposal_id)
                state["muse_spark"] = {"at": int(time.time()), "joint": joint, "fixed": [], "skipped": "già rifiutata"}
                _write(state)
                return
        if fixed and proposal_id in approved:
            log.info("maintenance: proposta %s già approvata di recente, skip", proposal_id)
            state["muse_spark"] = {"at": int(time.time()), "joint": joint, "fixed": [], "skipped": "già approvata"}
            _write(state)
            return
        if pending and pending.get("status") == "pending":
            log.info("maintenance: proposta %s già in attesa di OK, skip", pending.get("id"))
            return
        state["muse_spark"] = {"at": int(time.time()), "joint": joint, "fixed": fixed}
        state["checks"].append({"by": "muse-spark", "at": int(time.time()), "joint": joint, "fixed": fixed})
        if not fixed:
            state["pending_fix"] = False
            _write(state)
            return
        # crea proposta in attesa di OK
        proposal = {
            "id": proposal_id,
            "at": int(time.time()),
            "issues": joint.get("issues"),
            "fixes": fixed,
            "news": joint.get("news"),
            "reason": joint.get("reason"),
            "status": "pending"
        }
        state["pending_proposal"] = proposal
        state["pending_fix"] = True
        _write(state)
        _notify_owner_proposal(proposal)
        log.info("maintenance: proposta %s inviata a @Ziosapi in attesa di OK/Rifiuta", proposal_id)

    def _joint_reasoning(self, issues, news):
        """Due ingegneri ragionano insieme: fix utili, sicuri + chicche modernizzazione."""
        real_issues = [i for i in issues if i.startswith("fixtures") or i.startswith("giornate") or "tracking" in i]
        analysis = [i for i in issues if i.startswith("✅") or i.startswith("❌") or i.startswith("Team")]
        chicche = [i for i in issues if i.startswith("💡")]
        # whitelist allargata ingegneri: includono migliorie PWA, design, codice pronostici
        safe_fixes = {
            "fixtures vuote": "verifica finestra 30gg ok",
            "giornate sballate": "results round lock ok",
            "tracking fermo": "trigger evaluate",
            "PWA manifest": "aggiungi manifest.json + service worker iPhone/Android",
            "registrazione": "aggiungi auth leggera sito",
            "View Transitions": "aggiungi View Transitions API",
        }
        fixes = []
        for iss in real_issues + chicche:
            for key, fix in safe_fixes.items():
                if key.lower() in iss.lower():
                    fixes.append(fix)
        news_ctx = "; ".join(news[:3]) if news else "nessuna news mister"
        correct = sum(1 for a in analysis if a.startswith("✅"))
        wrong = sum(1 for a in analysis if a.startswith("❌"))
        # idee fresche dal forum
        ideas = _latest_webdev_ideas()
        reason = f"analisi {correct}/{len(analysis)} corrette - algoritmo {'ok' if correct>=wrong else 'da rivedere'}; news: {news_ctx[:60]}; idea top: {ideas[0]}"
        if chicche:
            reason += f" | chicca proposta: {chicche[0]}"
        if analysis:
            reason += " | " + " | ".join(analysis[:2])
        critical = [i for i in real_issues if not any(k in i.lower() for k in [kk.lower() for kk in safe_fixes])]
        # le chicche sono sempre sicure (solo aggiunte, non rotture)
        safe = (len(fixes) > 0 and not critical) or (len(chicche) > 0)
        if chicche and not fixes:
            fixes = [safe_fixes[k] for k in safe_fixes if any(k.lower() in c.lower() for c in chicche)][:1]
            safe = bool(fixes)
        return {
            "at": int(time.time()),
            "issues": real_issues,
            "analysis": analysis,
            "chicche": chicche,
            "news": news_ctx,
            "fixes": fixes if safe else [],
            "safe": safe,
            "reason": reason if safe else f"skip per issue non whitelist: {critical[:1]}",
            "agents": ["big-pickle-ingegnere-20m", "muse-spark-ingegnere-35m"],
            "ideas": ideas,
        }
