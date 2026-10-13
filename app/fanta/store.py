"""Rosa fanta per utente (kv: fanta.json).

Identità: `tg:<chat_id>` (bot) o `code:<code>` (sito, collegato via bot).
Ogni utente ha: rosa (lista giocatori), modulo, mod_dif, xi (titolari
scelti a coppi id), code (codice personale per accedere dal sito).
"""
import re
import threading

from app.core import kv

_lock = threading.RLock()
KEY = "fanta.json"
MODULI = ("4-3-3", "4-4-2", "3-5-2", "4-2-3-1", "3-4-3")
MOD_SLOTS = {
    "4-3-3": {"P": 1, "D": 4, "C": 3, "A": 3},
    "4-4-2": {"P": 1, "D": 4, "C": 4, "A": 2},
    "3-5-2": {"P": 1, "D": 3, "C": 5, "A": 2},
    "4-2-3-1": {"P": 1, "D": 4, "C": 5, "A": 1},
    "3-4-3": {"P": 1, "D": 3, "C": 4, "A": 3},
}


def load():
    data = kv.read_json(KEY)
    if not isinstance(data, dict):
        data = {}
    data.setdefault("users", {})
    data.setdefault("codes", {})
    return data


def save(data):
    kv.write_json(KEY, data)


def user_key_tg(chat_id):
    return f"tg:{chat_id}"


def normalize_code(code):
    code = re.sub(r"[^a-z0-9]", "", str(code or "").lower())
    return code[:12] if len(code) >= 3 else ""


def get_user(key):
    data = load()
    u = data["users"].get(key)
    return dict(u) if isinstance(u, dict) else None


def get_by_code(code):
    code = normalize_code(code)
    if not code:
        return None, None
    data = load()
    key = data["codes"].get(code)
    if not key:
        return None, None
    return key, get_user(key)


def upsert_user(key, **fields):
    data = load()
    u = data["users"].get(key)
    if not isinstance(u, dict):
        u = {}
    u.update(fields)
    data["users"][key] = u
    save(data)
    return dict(u)


def set_code(key, code):
    """Assegna/aggiorna codice personale. Restituisce il codice o None se preso."""
    code = normalize_code(code)
    if not code:
        return None
    with _lock:
        data = load()
        owner = data["codes"].get(code)
        if owner and owner != key:
            return None
        old = (data["users"].get(key) or {}).get("code")
        if old and old != code:
            data["codes"].pop(old, None)
        data["codes"][code] = key
        u = data["users"].setdefault(key, {})
        u["code"] = code
        save(data)
        return code


def add_player(key, player):
    """Aggiunge un giocatore alla rosa (dedup per id)."""
    pid = player.get("id")
    if pid is None:
        return False
    data = load()
    u = data["users"].setdefault(key, {})
    rosa = u.get("rosa") or []
    if any(p.get("id") == pid for p in rosa):
        return False
    rosa.append({
        "id": pid,
        "name": str(player.get("name") or "?"),
        "team": str(player.get("team") or "?"),
        "role": str(player.get("role") or "?"),
    })
    u["rosa"] = rosa
    save(data)
    return True


def remove_player(key, pid):
    data = load()
    u = data["users"].get(key)
    if not isinstance(u, dict):
        return False
    rosa = u.get("rosa") or []
    new = [p for p in rosa if p.get("id") != pid]
    if len(new) == len(rosa):
        return False
    u["rosa"] = new
    u["xi"] = [x for x in (u.get("xi") or []) if x != pid]
    save(data)
    return True


def set_xi(key, xi_ids):
    upsert_user(key, xi=list(xi_ids))
