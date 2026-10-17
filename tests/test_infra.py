"""Test dell'infrastruttura free (engine Actions + Worker + bot NxCreate).

Esegui:  python -m unittest tests.test_infra -v
Richiede node PATH (test parity Flask<->Worker).
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

STATE_SEED = {
    "version": 1, "updated": 1760000000,
    "season": {"id": "2026", "name": "Serie A 26/27"},
    "standings": [
        {"position": 1, "team_id": 1, "name": "Inter", "points": 15, "played": 5, "gf": 12, "ga": 4},
        {"position": 2, "team_id": 2, "name": "Napoli", "points": 13, "played": 5, "gf": 10, "ga": 5},
        {"position": 3, "team_id": 3, "name": "Milan", "points": 11, "played": 5, "gf": 9, "ga": 6},
        {"position": 4, "team_id": 4, "name": "Juventus", "points": 9, "played": 5, "gf": 7, "ga": 7},
    ],
    "fixtures": [
        {"id": "m1", "home": "Inter", "away": "Napoli", "start_ts": 1760010000,
         "round": 6, "status": "notstarted",
         "predictions": {
             "1x2": {"1": 0.48, "x": 0.27, "2": 0.25},
             "model_picks": {"1x2": {"key": "1", "pick": "1", "prob": 0.48, "odds": 1.90}},
             "exact_score": [{"score": "2-1", "prob": 0.12}],
             "best_bets": [{"pick": "1", "odds": 1.90, "prob": 0.48, "fair": 2.08, "edge": 0.08}],
         }},
        {"id": "m2", "home": "Milan", "away": "Juventus", "start_ts": 1760020000,
         "round": 6, "status": "notstarted",
         "predictions": {
             "1x2": {"1": 0.36, "x": 0.30, "2": 0.34},
             "model_picks": {"1x2": {"key": "x", "pick": "x", "prob": 0.30, "odds": 3.20}},
             "exact_score": [],
             "best_bets": [],
         }},
    ],
    "results": [
        {"round": 4, "matches": [
            {"id": "m9", "home": "Napoli", "away": "Milan", "score": "2-1", "hs": 2, "as": 1}]},
        {"round": 5, "matches": [
            {"id": "m1", "home": "Inter", "away": "Napoli", "score": "2-1", "hs": 2, "as": 1},
            {"id": "m2", "home": "Milan", "away": "Juventus", "score": "1-1", "hs": 1, "as": 1}]},
    ],
    "schedina": {
        "round": 6, "created_at": 1759990000,
        "picks": [
            {"fixture_id": "m1", "home": "Inter", "away": "Napoli", "market": "1x2",
             "pick": "1", "odds": 1.90, "prob": 0.48, "result": "win", "score": "2-1"},
            {"fixture_id": "m2", "home": "Milan", "away": "Juventus", "market": "over_under",
             "pick": "over_2.5", "odds": 1.85, "prob": 0.55, "result": None, "score": None},
        ],
        "history": [
            {"round": 5, "picks": [
                {"fixture_id": "m1", "market": "1x2", "pick": "1"}], "wins": 1, "losses": 0},
            {"round": 5, "picks": [
                {"fixture_id": "m1", "market": "1x2", "pick": "1"}], "wins": 1, "losses": 0},
            {"round": 4, "picks": [
                {"fixture_id": "m9", "market": "btts", "pick": "si"}], "wins": 0, "losses": 1},
        ],
    },
    "engine": {"last_run_ts": 1760000000, "last_run_ok": True, "host": "github-actions"},
}

COMMUNITY_SEED = {
    "rounds": {
        "6": {"entries": {
            "ip:test-ip": {"picks": [
                {"fixture_id": "m1", "home": "Inter", "away": "Napoli",
                 "market": "1x2", "pick": "1", "result": None, "score": None}],
                "ts": 1759995000},
            "ip:altro": {"picks": [
                {"fixture_id": "m1", "home": "Inter", "away": "Napoli",
                 "market": "1x2", "pick": "2", "result": None, "score": None}],
                "ts": 1759996000},
        }},
        "4": {"entries": {
            "ip:test-ip": {"picks": [
                {"fixture_id": "m9", "home": "Napoli", "away": "Milan",
                 "market": "1x2", "pick": "1", "result": "win", "score": "2-1"}],
                "ts": 1759000000},
        }},
    }
}

LEARNING_SEED = {
    "records": [
        {"id": "m9", "home": "Napoli", "away": "Milan", "round": 4,
         "start_ts": 1759000000, "evaluated": True,
         "result": {"1x2": "1", "over_under": "over_2.5", "btts": "si",
                    "home_score": 2, "away_score": 1},
         "picks": [{"market": "1x2", "pick": "1", "odds": 1.80, "prob": 0.52}],
         "bets": [{"market": "over_under", "pick": "over_2.5", "odds": 1.90, "prob": 0.57}]},
        {"id": "m1", "home": "Inter", "away": "Napoli", "round": 5,
         "start_ts": 1759900000, "evaluated": True,
         "result": {"1x2": "1", "over_under": "over_2.5", "btts": "si",
                    "home_score": 2, "away_score": 1},
         "picks": [], "bets": [{"market": "1x2", "pick": "x", "odds": 3.10, "prob": 0.28}]},
        {"id": "m2", "home": "Milan", "away": "Juventus", "round": 6,
         "start_ts": 1760020000, "evaluated": False,
         "picks": [{"market": "1x2", "pick": "x", "prob": 0.30}], "bets": []},
    ],
    "tracking": {}, "calibration": {},
}


def _write_seed(d):
    for name, data in (("state.json", STATE_SEED),
                       ("community.json", COMMUNITY_SEED),
                       ("learning.json", LEARNING_SEED)):
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)


def _load_cmd(name):
    path = os.path.join(ROOT, "infra", "nxcreate", "commands", name + ".py")
    spec = importlib.util.spec_from_file_location("nxc_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestEngineHeadless(unittest.TestCase):
    def test_engine_import_no_flask_no_telegram(self):
        """engine.py deve importare senza trainare Flask ne' il bot Telegram."""
        code = ("import sys, os; sys.path.insert(0, os.getcwd()); import engine; "
                "bad = [m for m in ('app.telegram', 'app.web.server') "
                "if m in sys.modules]; "
                "print('BAD=' + ','.join(bad)); "
                "assert not bad, bad")
        r = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertIn("BAD=", r.stdout)

    def test_lock_acquire_contend_release(self):
        import engine
        from app.core import kv

        class FakeRedis:
            def __init__(self):
                self.d = {}
            def set(self, k, v, nx=False, ex=None):
                if nx and k in self.d:
                    return None
                self.d[k] = v
                return True
            def get(self, k):
                return self.d.get(k)
            def delete(self, k):
                self.d.pop(k, None)

        fake = FakeRedis()
        orig = kv._redis
        kv._redis = lambda: fake
        try:
            owner = engine._acquire_lock()
            self.assertTrue(owner)
            self.assertIsNone(engine._acquire_lock(), "secondo acquire deve fallire")
            engine._release_lock(owner)
            owner2 = engine._acquire_lock()
            self.assertTrue(owner2, "dopo release si riprende il lock")
            engine._release_lock(owner2)
            self.assertNotIn(engine.LOCK_KEY, fake.d)
        finally:
            kv._redis = orig


class TestLearningPersistence(unittest.TestCase):
    def test_learning_survives_process_restart(self):
        """learning.json scritto da un processo run_cycle e' leggibile dal
        successivo: prerequisito della persistenza Upstash (stesso kv)."""
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "DATA_DIR": d, "REDIS_URL": ""}
            w = ("import sys, os; sys.path.insert(0, os.getcwd()); "
                 "from app.analysis import tracker; "
                 "d = tracker.load(); "
                 "d['records'].append({'id': 'x1', 'evaluated': True}); "
                 "tracker.save(d); "
                 "print('WROTE', len(d['records']))")
            r = subprocess.run([sys.executable, "-c", w], cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr[-1000:])
            self.assertIn("WROTE 1", r.stdout)
            r2 = subprocess.run(
                [sys.executable, "-c",
                 "import sys, os; sys.path.insert(0, os.getcwd()); "
                 "from app.analysis import tracker; "
                 "d = tracker.load(); print('READ', len(d['records']), "
                 "d['records'][0]['id'])"],
                cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(r2.returncode, 0, r2.stderr[-1000:])
            self.assertIn("READ 1 x1", r2.stdout)


class TestParity(unittest.TestCase):
    """Il Worker (JS) e il server Flask devono produrre lo stesso JSON."""

    @classmethod
    def setUpClass(cls):
        cls._d = tempfile.TemporaryDirectory()
        d = cls._d.name
        _write_seed(d)
        env = {**os.environ, "DATA_DIR": d, "REDIS_URL": ""}
        cls.flask = subprocess.run(
            [sys.executable, os.path.join(ROOT, "tests", "_parity_flask.py"), d],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
        cls.node = subprocess.run(
            ["node", os.path.join(ROOT, "infra", "cloudflare", "test_api.mjs"), d],
            cwd=ROOT, capture_output=True, text=True, timeout=60)

    @classmethod
    def tearDownClass(cls):
        cls._d.cleanup()

    def _both(self):
        self.assertEqual(self.flask.returncode, 0, self.flask.stderr[-2000:])
        self.assertEqual(self.node.returncode, 0, self.node.stderr[-2000:])
        return (json.loads(self.flask.stdout),
                json.loads(self.node.stdout))

    def test_schedina_identica(self):
        f, n = self._both()
        self.assertEqual(f["schedina"], n["schedina"])

    def test_schedina_dedupe_storico(self):
        _, n = self._both()
        rounds = [h["round"] for h in n["schedina"]["history"]]
        self.assertEqual(rounds, [4], "le voci duplicate della giornata 5 devono cadere")

    def test_community_identica(self):
        f, n = self._both()
        self.assertEqual(f["community"], n["community"])

    def test_community_valuta_contro_risultati(self):
        _, n = self._both()
        mine = {p["fixture_id"]: p for p in n["community"]["my"]["picks"]}
        self.assertEqual(mine["m1"]["result"], "win")
        self.assertEqual(mine["m1"]["score"], "2-1")
        self.assertEqual(n["community"]["participants"], 2)

    def test_tracking_identico(self):
        f, n = self._both()
        self.assertEqual(f["tracking"], n["tracking"])
        self.assertEqual(f["tracking"]["tracked"], 3)
        self.assertEqual(f["tracking"]["evaluated"], 2)


class TestBotParity(unittest.TestCase):
    """I formattori del bot NxCreate mostrano gli stessi dati della API."""

    def test_schedina(self):
        from app.analysis.schedina import _dedupe_history
        mod = _load_cmd("schedina")
        # il bot riceve /api/schedina: storico gia' deduplicato dalla API
        slip_api = json.loads(json.dumps(STATE_SEED["schedina"]))
        slip_api["history"] = _dedupe_history(slip_api["history"])
        txt = mod.fmt_schedina(slip_api)
        self.assertIn("Schedina giornata 6", txt)
        self.assertIn("Inter - Napoli", txt)
        self.assertIn("✅", txt)
        self.assertIn("2-1", txt)
        self.assertIn("over 2.5", txt)
        self.assertIn("1 vinti · 0 persi", txt)
        self.assertIn("Giornata 4", txt)
        self.assertNotIn("Giornata 5", txt)   # duplicate rimosse

    def test_classifica(self):
        mod = _load_cmd("classifica")
        txt = mod.fmt_classifica(STATE_SEED)
        self.assertIn("Classifica Serie A", txt)
        self.assertIn("Inter", txt)
        self.assertIn("15pt", txt)

    def test_pronostici(self):
        mod = _load_cmd("pronostici")
        txt = mod.fmt_pronostici(STATE_SEED)
        self.assertIn("Inter - Napoli", txt)
        self.assertIn("🎯", txt)
        self.assertIn("💰", txt)
        self.assertIn("1.90", txt)

    def test_risultati(self):
        mod = _load_cmd("risultati")
        txt = mod.fmt_risultati(STATE_SEED)
        self.assertIn("Inter 2-1 Napoli", txt)
        self.assertIn("Giornata 5", txt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
