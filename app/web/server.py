"""Server web: dashboard + API JSON dello stato."""
import logging
import os
import secrets

from flask import Flask, jsonify, request, send_from_directory, session, redirect, url_for, render_template_string

import config
from app.analysis.assistant import answer
from app.analysis.llm import ask_ai
from app.core import kv
from app.core.store import Store

log = logging.getLogger("web")

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

LOGIN_HTML = """<!DOCTYPE html>
<html lang="it"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Serie A - Login</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0e1a;color:#eef2ff;font-family:Inter,system-ui,sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center}
.card{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);border-radius:16px;padding:40px;width:100%;max-width:400px;margin:20px}
h1{text-align:center;margin-bottom:8px;font-size:1.5rem}
.sub{text-align:center;color:#94a3b8;margin-bottom:24px;font-size:.9rem}
label{display:block;margin-bottom:6px;font-size:.85rem;color:#94a3b8}
input{width:100%;padding:10px 14px;border-radius:8px;border:1px solid rgba(255,255,255,.1);background:rgba(255,255,255,.06);color:#eef2ff;font-size:.95rem;margin-bottom:16px}
input:focus{outline:none;border-color:#34d399}
button{width:100%;padding:12px;border:none;border-radius:8px;background:#34d399;color:#0a0e1a;font-weight:600;font-size:1rem;cursor:pointer}
button:hover{opacity:.9}
.error{background:rgba(248,113,113,.15);border:1px solid rgba(248,113,113,.3);color:#f87171;padding:10px;border-radius:8px;margin-bottom:16px;font-size:.85rem;text-align:center}
.switch{text-align:center;margin-top:16px;font-size:.85rem;color:#94a3b8}
.switch a{color:#34d399;text-decoration:none}
</style>
</head><body>
<div class="card">
<h1>Serie A Stats</h1>
<p class="sub">Accedi al tuo account</p>
{% if error %}<div class="error">{{ error }}</div>{% endif %}
<form method="POST" action="/login">
<label>Email</label>
<input type="email" name="email" required placeholder="tu@email.com">
<label>Password</label>
<input type="password" name="password" required placeholder="Min 6 caratteri">
<button type="submit">Accedi</button>
</form>
<div class="switch">Non hai un account? <a href="/register">Registrati</a></div>
</div>
</body></html>"""

REGISTER_HTML = """<!DOCTYPE html>
<html lang="it"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Serie A - Registrazione</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0e1a;color:#eef2ff;font-family:Inter,system-ui,sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center}
.card{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);border-radius:16px;padding:40px;width:100%;max-width:400px;margin:20px}
h1{text-align:center;margin-bottom:8px;font-size:1.5rem}
.sub{text-align:center;color:#94a3b8;margin-bottom:24px;font-size:.9rem}
label{display:block;margin-bottom:6px;font-size:.85rem;color:#94a3b8}
input{width:100%;padding:10px 14px;border-radius:8px;border:1px solid rgba(255,255,255,.1);background:rgba(255,255,255,.06);color:#eef2ff;font-size:.95rem;margin-bottom:16px}
input:focus{outline:none;border-color:#34d399}
button{width:100%;padding:12px;border:none;border-radius:8px;background:#60a5fa;color:#0a0e1a;font-weight:600;font-size:1rem;cursor:pointer}
button:hover{opacity:.9}
.error{background:rgba(248,113,113,.15);border:1px solid rgba(248,113,113,.3);color:#f87171;padding:10px;border-radius:8px;margin-bottom:16px;font-size:.85rem;text-align:center}
.ok{background:rgba(52,211,153,.15);border:1px solid rgba(52,211,153,.3);color:#34d399;padding:10px;border-radius:8px;margin-bottom:16px;font-size:.85rem;text-align:center}
.switch{text-align:center;margin-top:16px;font-size:.85rem;color:#94a3b8}
.switch a{color:#60a5fa;text-decoration:none}
</style>
</head><body>
<div class="card">
<h1>Serie A Stats</h1>
<p class="sub">Crea un nuovo account</p>
{% if error %}<div class="error">{{ error }}</div>{% endif %}
{% if ok %}<div class="ok">{{ ok }}</div>{% endif %}
<form method="POST" action="/register">
<label>Email</label>
<input type="email" name="email" required placeholder="tu@email.com">
<label>Nome visualizzato</label>
<input type="text" name="display_name" placeholder="Opzionale">
<label>Password</label>
<input type="password" name="password" required placeholder="Min 6 caratteri">
<button type="submit">Registrati</button>
</form>
<div class="switch">Hai già un account? <a href="/login">Accedi</a></div>
</div>
</body></html>"""


def create_app(store: Store, tunnel=None):
    app = Flask(__name__, static_folder=None)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

    def login_required(f):
        from functools import wraps
        @wraps(f)
        def decorated(*args, **kwargs):
            if "user" not in session:
                return redirect(url_for("login_page"))
            return f(*args, **kwargs)
        return decorated

    @app.get("/login")
    def login_page():
        return render_template_string(LOGIN_HTML, error=None)

    @app.post("/login")
    def login_post():
        from app.auth import login
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        user, msg = login(email, password)
        if not user:
            return render_template_string(LOGIN_HTML, error=msg)
        session["user"] = user["email"]
        session["display_name"] = user.get("display_name", "")
        return redirect("/")

    @app.get("/register")
    def register_page():
        return render_template_string(REGISTER_HTML, error=None, ok=None)

    @app.post("/register")
    def register_post():
        from app.auth import register
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        display_name = request.form.get("display_name", "").strip()
        ok, msg = register(email, password, display_name)
        if not ok:
            return render_template_string(REGISTER_HTML, error=msg, ok=None)
        return render_template_string(REGISTER_HTML, error=None, ok=msg + " Ora puoi accedere.")

    @app.get("/logout")
    def logout():
        session.clear()
        return redirect("/login")

    @app.get("/")
    @login_required
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/<path:path>")
    @login_required
    def assets(path):
        resp = send_from_directory(STATIC_DIR, path)
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.get("/api/state")
    def api_state():
        return jsonify(store.data)

    @app.get("/api/health")
    def api_health():
        return jsonify({"ok": True, "updated": store.get("updated", 0)})

    @app.get("/healthz")
    def healthz():
        """Health check leggero per Render (keepalive/ping esterno)."""
        return jsonify({"ok": True, "updated": store.get("updated", 0)})

    @app.get("/api/results")
    def api_results():
        """Risultati delle giornate della stagione (superleggero)."""
        return jsonify({"updated": store.get("updated", 0),
                        "results": store.get("results", [])})

    @app.get("/api/schedina")
    def api_schedina():
        """Schedina della giornata + storico con contatori vinti/persi."""
        from app.analysis import schedina
        slip = store.get("schedina") or {}
        picks = slip.get("picks") or []
        wins = sum(1 for p in picks if p.get("result") == "win")
        losses = sum(1 for p in picks if p.get("result") == "loss")
        return jsonify({
            "round": slip.get("round"), "created_at": slip.get("created_at"),
            "wins": wins, "losses": losses, "picks": picks,
            "history": slip.get("history", []),
        })

    @app.get("/api/tracking-records")
    def api_tracking_records():
        """Record valutati dal tracker: pick/best-bet vs esito reale (debug)."""
        from app.analysis import tracker
        data = tracker.load()
        out = []
        for r in data["records"]:
            if not r.get("evaluated"):
                continue
            res = r.get("result") or {}
            hits = []
            for b in r.get("bets", []):
                mkt, pick = b.get("market"), b.get("pick")
                hit = pick == res.get(mkt)
                hits.append({"market": mkt, "pick": pick, "odds": b.get("odds"),
                             "prob": b.get("prob"), "hit": hit})
            for pi in r.get("picks", []):
                mkt, pick = pi.get("market"), pi.get("pick")
                hit = pick == res.get(mkt)
                hits.append({"market": mkt, "pick": pick, "odds": pi.get("odds"),
                             "prob": pi.get("prob"), "hit": hit, "model": True})
            out.append({
                "id": r.get("id"), "home": r.get("home"), "away": r.get("away"),
                "round": r.get("round"), "start_ts": r.get("start_ts"),
                "score": f"{res.get('home_score')}-{res.get('away_score')}",
                "result": res.get("1x2"), "hits": hits})
        out.sort(key=lambda x: -(x.get("start_ts") or 0))
        return jsonify({"tracked": len(data["records"]),
                        "evaluated": len(out), "records": out})

    @app.post("/api/tracking-import")
    def api_tracking_import():
        """Unisce nel ledger (Redis) i record valutati inviati dall'istanza
        locale. Usato una sola volta per ripristinare le valutazioni del
        13/09 perse tra Redis e locale. Mantiene entrambi gli id (es. in
        caso di duplicati lo-fixture): preferisce il record già valutato."""
        # auth: solo owner o token segreto per evitare avvelenamento learning.json
        auth = request.headers.get("X-Import-Token") or request.args.get("token") or ""
        expected = os.environ.get("IMPORT_TOKEN") or ""
        if expected and auth != expected:
            # fallback: check Telegram owner via simple header chat_id
            try:
                cid = int(request.headers.get("X-Chat-Id") or 0)
                if cid not in (config.TELEGRAM_OWNER_IDS or []):
                    return jsonify({"error": "unauthorized"}), 401
            except (ValueError, TypeError):
                return jsonify({"error": "unauthorized"}), 401
        from app.analysis import tracker
        payload = request.get_json(silent=True) or {}
        incoming = payload.get("records")
        if isinstance(incoming, list) and len(incoming) > 200:
            return jsonify({"error": "troppi records (max 200)"}), 400
        if not isinstance(incoming, list):
            return jsonify({"error": "manca records[]"}), 400
        def _picks(r):
            if r.get("picks"):
                return r["picks"]
            out = []
            for m, probs in (r.get("probs") or {}).items():
                if not isinstance(probs, dict) or not probs:
                    continue
                key = max(probs, key=lambda k: probs[k] or 0)
                if key and probs.get(key):
                    out.append({"market": m, "pick": key, "prob": probs[key]})
            return out
        data = tracker.load()
        by_id = {r.get("id"): r for r in data["records"]}
        added = replaced = 0
        for inc in incoming:
            if not inc.get("id"):
                continue
            cur = by_id.get(inc["id"])
            if cur is None:
                inc = dict(inc)
                if not inc.get("picks"):
                    inc["picks"] = _picks(inc)
                data["records"].append(inc)
                by_id[inc["id"]] = inc
                added += 1
            elif inc.get("evaluated") and not cur.get("evaluated"):
                cur.update(inc)
                if not cur.get("picks"):
                    cur["picks"] = _picks(cur)
                replaced += 1
        if added or replaced:
            tracker.save(data)
        return jsonify({"added": added, "replaced": replaced,
                        "total": len(data["records"])})

    @app.post("/api/tracking-renotify")
    def api_tracking_renotify():
        """Retest notifiche: azzera win_notified della schedina e reinvia."""
        # auth come sopra
        auth = request.headers.get("X-Import-Token") or request.args.get("token") or ""
        expected = os.environ.get("IMPORT_TOKEN") or ""
        if expected and auth != expected:
            try:
                cid = int(request.headers.get("X-Chat-Id") or 0)
                if cid not in (config.TELEGRAM_OWNER_IDS or []):
                    return jsonify({"error": "unauthorized"}), 401
            except (ValueError, TypeError):
                return jsonify({"error": "unauthorized"}), 401
        from app.analysis import schedina
        from app import notify
        slip = store.get("schedina") or {}
        n = 0
        for entry in [slip] + (slip.get("history") or []):
            for p in entry.get("picks") or []:
                if p.get("win_notified"):
                    p["win_notified"] = False
                    n += 1
        if n:
            store.set("schedina", slip)
        pending = schedina.pending_wins(store)
        if pending:
            notify.send_pending_wins(store)
        return jsonify({"reset": n, "pending": len(pending)})

    @app.get("/api/live")
    def api_live():
        """Partite in corso + follow dello stato (leggero, pollato ogni ~10s)."""
        live = store.get("live")
        if not live:
            return jsonify({"updated": 0, "matches": []})
        return jsonify(live)

    @app.post("/api/ask")
    def api_ask():
        """Chiede all'assistente AI una raccomandazione basata sui dati."""
        payload = request.get_json(silent=True) or {}
        question = (payload.get("question") or "").strip()
        if not question:
            return jsonify({"error": "nessuna domanda"}), 400
        fixtures = [f for f in store.get("fixtures", [])]
        standings = store.get("standings", [])
        result = ask_ai(question, fixtures, standings)
        if result is None:
            result = answer(question, fixtures)
        return jsonify(result)

    @app.get("/api/tunnel")
    def api_tunnel():
        if tunnel is None:
            return jsonify({"available": False, "running": False, "url": None})
        return jsonify({"available": tunnel.available, **tunnel.status()})

    @app.get("/api/tg-info")
    def api_tg_info():
        """Link al bot Telegram per il bottone sul sito."""
        link = config.TELEGRAM_BOT_LINK
        if link:
            return jsonify({"link": link})
        # prova a ricavare username dal bot se già online (store live)
        username = store.get("tg_username")
        if username:
            # username già con @
            handle = username.lstrip("@")
            return jsonify({"link": f"https://t.me/{handle}"})
        return jsonify({"link": None})

    @app.get("/telegram")
    def telegram_redirect():
        """Redirect diretto a Telegram per /telegram."""
        from flask import redirect
        link = config.TELEGRAM_BOT_LINK
        if not link:
            username = store.get("tg_username")
            if username:
                link = f"https://t.me/{username.lstrip('@')}"
        if link:
            return redirect(link, code=302)
        return jsonify({"error": "Telegram bot non configurato (TELEGRAM_BOT_LINK)"}), 404

    @app.get("/api/test-notify")
    def api_test_notify():
        """Manda subito un test a @Ziosapi con tasti OK/Rifiuta."""
        if request.args.get("token") != os.environ.get("MAINTENANCE_TOKEN", "test123"):
            return jsonify({"error": "token errato"}), 403
        try:
            from app.maintenance import _notify_owner_proposal
            is_design = request.args.get("design") == "1"
            if is_design:
                proposal = {
                    "id": "design999",
                    "issues": ["PWA manifest mancante - sito non installabile su iPhone/Android"],
                    "fixes": ["aggiungi manifest.json + service worker iPhone/Android"],
                    "news": "Idea ingegnere: PWA installabile + View Transitions API (da Hacker News)",
                    "reason": "chicca design ingegnere: migliora installazione mobile, proposta sicura",
                }
            else:
                proposal = {
                    "id": "test123",
                    "issues": ["fixtures vuote (test)"],
                    "fixes": ["verifica finestra 30gg ok"],
                    "news": "Test mister: Gasperini carica la Roma",
                    "reason": "test manuale - verifica bot @Ziosapi",
                }
            _notify_owner_proposal(proposal)
            # salva come pending così puoi fare OK/Rifiuta anche sul test design
            try:
                from app.maintenance import _read, _write
                import time
                state = _read()
                state["pending_proposal"] = {**proposal, "at": int(time.time()), "status": "pending"}
                state["pending_fix"] = True
                _write(state)
            except:
                pass
            return jsonify({"ok": True, "sent_to": config.TELEGRAM_OWNER_IDS or ["@Ziosapi"], "proposal": proposal})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.get("/api/test-maintenance")
    def api_test_maintenance():
        """Forza Big Pickle + Muse Spark subito e manda proposta a @Ziosapi."""
        if request.args.get("token") != os.environ.get("MAINTENANCE_TOKEN", "test123"):
            return jsonify({"error": "token errato, usa ?token=test123 o imposta MAINTENANCE_TOKEN"}), 403
        try:
            from app.maintenance import BigPickleAgent, MuseSparkAgent
            bp = BigPickleAgent(store); bp.tick()
            ms = MuseSparkAgent(store); ms.tick()
            from app.maintenance import _read
            return jsonify({"ok": True, "maintenance": _read()})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.get("/api/net-test")
    def api_net_test():
        """Test diretto (no Tor) dei host dati: utile per saggiare quale
        fonte risponde davvero dal datacenter Render."""
        import time as _time
        import requests as _requests
        hosts = {
            "espn_core":  "https://sports.core.api.espn.com/v2/sports/soccer/leagues/ita.1",
            "espn_web":   "https://site.web.api.espn.com/apis/v2/sports/soccer/ita.1/standings",
            "sofascore":  "https://www.sofascore.com/api/v1/sport/football/events/live",
        }
        out = {}
        for name, url in hosts.items():
            t = _time.time()
            try:
                r = _requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                out[name] = {"status": r.status_code, "ms": round((_time.time() - t) * 1000)}
            except Exception as e:
                out[name] = {"status": "ERR", "ms": round((_time.time() - t) * 1000), "err": str(e)[:80]}
        t = _time.time()
        try:
            from app.sources.espn import EspnClient
            c = EspnClient()
            res = c.season_results("2026")
            out["espn_results"] = {"all": sum(len(r.get("matches", [])) for r in res)}
        except Exception as e:
            out["espn_results"] = {"all": -1, "err": str(e)[:200]}
        return jsonify(out)

    @app.get("/api/debug-codegen")
    def api_debug_codegen():
        from app.analysis.codegen import _api_key, GEMINI_BASE, MODELS, SYSTEM_PROMPT, _parse_response
        import requests as req
        key = _api_key()
        if not key:
            return jsonify({"error": "GEMINI_API_KEY non impostata", "key_set": False})
        results = {}
        for model in MODELS:
            url = "%s/%s:generateContent?key=%s" % (GEMINI_BASE, model, key)
            payload = {
                "contents": [{"role": "user", "parts": [{"text": "RICHIEDI: cambia il colore del body in rosso\n\nFILE ATTUALI:\n=== app/web/static/style.css ===\nbody { background: #1a1a2e; color: white; }\n=== FINE ==="}]}],
                "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "generationConfig": {"maxOutputTokens": 4096, "temperature": 0.2},
            }
            try:
                r = req.post(url, json=payload, timeout=60)
                raw = r.json()
                text = ""
                candidates = raw.get("candidates") or []
                if candidates and isinstance(candidates[0], dict):
                    parts = candidates[0].get("content", {}).get("parts", [])
                    text = parts[0].get("text", "") if parts else ""
                parsed = _parse_response(text) if text else []
                results[model] = {
                    "status": r.status_code,
                    "raw_len": len(text),
                    "raw_preview": text[:500] if text else "",
                    "parsed": len(parsed),
                }
            except Exception as e:
                results[model] = {"error": str(e)[:200]}
        return jsonify({"key_set": True, "key_len": len(key), "results": results})

    @app.get("/api/test-firecrawl")
    def api_test_firecrawl():
        from app.analysis.firecrawl_direttagoal import scrape_classifica, scrape_risultati
        results = {}
        try:
            c = scrape_classifica()
            results["classifica"] = {"ok": c is not None, "rows": len(c) if c else 0, "preview": str(c)[:300] if c else ""}
        except Exception as e:
            results["classifica"] = {"error": str(e)[:200]}
        try:
            r = scrape_risultati()
            results["risultati"] = {"ok": bool(r), "count": len(r), "preview": str(r)[:300] if r else ""}
        except Exception as e:
            results["risultati"] = {"error": str(e)[:200]}
        return jsonify(results)

    return app