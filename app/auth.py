"""Autenticazione utente: registrazione, login, sessioni.

Usa werkzeug per hash password e Flask sessions.
Utenti salvati in users.json (Redis o disco).
"""
import json
import logging
import os
import time

from werkzeug.security import generate_password_hash, check_password_hash

log = logging.getLogger("auth")

_USERS_FILE = "users.json"

_users_cache = None
_users_path = None


def _get_path():
    global _users_path
    if _users_path is None:
        from app.core import kv
        _users_path = kv._dir() / _USERS_FILE
    return _users_path


def _load():
    global _users_cache
    if _users_cache is not None:
        return _users_cache
    fp = _get_path()
    if fp.exists():
        try:
            _users_cache = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            _users_cache = {}
    else:
        _users_cache = {}
    return _users_cache


def _save():
    global _users_cache
    fp = _get_path()
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(_users_cache or {}, indent=2, ensure_ascii=False), encoding="utf-8")


def register(email, password, display_name=None):
    """Registra un nuovo utente. Ritorna (ok, msg)."""
    users = _load()
    email = email.strip().lower()
    if not email or not password:
        return False, "Email e password obbligatorie"
    if len(password) < 6:
        return False, "Password minimo 6 caratteri"
    if email in users:
        return False, "Email già registrata"
    users[email] = {
        "email": email,
        "display_name": display_name or email.split("@")[0],
        "password": generate_password_hash(password),
        "created": int(time.time()),
        "telegram_chat_id": None,
    }
    _save()
    log.info("auth: registrato %s", email)
    return True, "Registrazione completata"


def login(email, password):
    """Verifica credenziali. Ritorna (user_dict o None, msg)."""
    users = _load()
    email = email.strip().lower()
    user = users.get(email)
    if not user:
        return None, "Email non trovata"
    if not check_password_hash(user["password"], password):
        return None, "Password errata"
    log.info("auth: login %s", email)
    return user, "Login effettuato"


def get_user(email):
    """Restituisce user dict o None."""
    users = _load()
    return users.get(email.strip().lower())


def link_telegram(email, chat_id):
    """Collega un account web a un chat_id Telegram."""
    users = _load()
    email = email.strip().lower()
    if email in users:
        users[email]["telegram_chat_id"] = chat_id
        _save()
        return True
    return False
