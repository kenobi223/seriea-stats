"""Side Flask del test di parity (gira come subprocess con DATA_DIR isolate).

Seede state.json/community.json/learning.json su disco, apre create_app e
espone le stesse API del Worker. Stampa su stdout il JSON:
  {schedina, community, tracking}
Uso: python _parity_flask.py <seed_dir>
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

seed_dir = sys.argv[1]
os.environ["DATA_DIR"] = seed_dir          # deve precedere import config

# copia i seed sui path attesi da kv (kv.py usa config.DATA_DIR gia' puntato
# al seed dir, quindi basta importare)
import config  # noqa: E402
from app.core.store import Store  # noqa: E402
from app.web.server import create_app  # noqa: E402

store = Store()
store.load()
app = create_app(store)
client = app.test_client()

schedina = client.get("/api/schedina").get_json()
community = client.get("/api/community", headers={"X-Forwarded-For": "test-ip"}).get_json()
tracking = client.get("/api/tracking-records").get_json()

sys.stdout.write(json.dumps({
    "schedina": schedina,
    "community": community,
    "tracking": {"tracked": tracking["tracked"],
                 "evaluated": tracking["evaluated"],
                 "records": tracking["records"]},
}, ensure_ascii=False))
