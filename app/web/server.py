"""Server web: dashboard + API JSON dello stato."""
import logging
import os

from flask import Flask, jsonify, request, send_from_directory

import config
from app.analysis.assistant import answer
from app.analysis.llm import ask_ai
from app.core import kv
from app.core.store import Store

log = logging.getLogger("web")

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def create_app(store: Store, tunnel=None):
    app = Flask(__name__, static_folder=None)

    @app.get("/")
    def index():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/<path:path>")
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
        from app.analysis import tracker
        payload = request.get_json(silent=True) or {}
        incoming = payload.get("records")
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

    @app.get("/api/live")
    def api_live():
        """Partite in corso + follow dello stato (leggero, pollato ogni ~10s)."""
        live = store.get("live")
        if not live:
            return jsonify({"updated": 0, "matches": []})
        return jsonify(live)

    @app.post("/api/odds")
    def api_add_odds():
        """Aggiunge una quota manuale (proprio per i mercati giocatore es.
        'Lautaro Tiro in porta' che i comparatori non coprono)."""
        payload = request.get_json(silent=True) or {}
        required = ("home", "away", "market", "pick", "source", "odds")
        if not all(k in payload for k in required):
            return jsonify({"error": "servono: home, away, market, pick, source, odds"}), 400
        entry = {
            "home": payload["home"], "away": payload["away"],
            "market": payload["market"], "pick": payload["pick"],
            "source": payload["source"], "odds": float(payload["odds"]),
        }
        try:
            manual = kv.read_json("manual_odds.json", default=[])
        except Exception:
            manual = []
        if not isinstance(manual, list):
            manual = []
        manual.append(entry)
        kv.write_json("manual_odds.json", manual)
        log.info("quota manuale aggiunta: %s", entry)
        return jsonify({"ok": True, "total": len(manual)})

    @app.get("/api/manual-odds")
    def api_manual_odds():
        data = kv.read_json("manual_odds.json", default=[])
        return jsonify(data if isinstance(data, list) else [])

    @app.delete("/api/manual-odds")
    def api_clear_manual_odds():
        kv.write_json("manual_odds.json", [])
        return jsonify({"ok": True})

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

    return app