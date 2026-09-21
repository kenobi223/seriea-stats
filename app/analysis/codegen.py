"""Code generation via OpenCode Zen per /opencode.

L'owner chiede un fix, il LLM legge il codice sorgente e genera
le modifiche reali. Le fix vengono applicate ai file e pushate.
"""
import json
import logging
import os
import pathlib
import re
import time

import requests

log = logging.getLogger("codegen")

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
MODELS = ["gemini-3.1-flash-lite", "gemini-3.8-flash", "gemini-3.5-flash"]

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
STATIC = PROJECT_ROOT / "app" / "web" / "static"

# File che il LLM può leggere/modificare
READABLE_FILES = [
    "app/web/static/index.html",
    "app/web/static/style.css",
    "app/web/static/app.js",
    "app/web/static/manifest.json",
    "app/web/static/sw.js",
    "app/web/static/logo.svg",
    "app/telegram.py",
    "app/maintenance.py",
    "config.py",
]

SYSTEM_PROMPT = """Sei un ingegnere software senior. Modifica il codice di un'app web Serie A.

REGOLE:
1. Leggi il file fornito nel contesto
2. Genera SOLO le modifiche necessarie
3. Rispondi ESCLUSIVAMENTE in JSON (senza markdown, senza ```, senza commenti):

[{"path": "percorso/file", "content": "intero contenuto del file MODIFICATO"}]

4. Il content deve essere il FILE INTERO modificato, non snippet
5. Massimo 1 file per richiesta
6. NON cambiare logica pronostici (predictor/tracker)
7. NON rimuovere funzionalità
8. Mantieni lo stile esistente
9. Se il file è lungo,专注 sulle modifiche richieste"""


def _api_key():
    return os.environ.get("GEMINI_API_KEY")


def _read_files(paths):
    """Legge i file del progetto e restituisce il contesto."""
    parts = []
    for p in paths:
        fp = PROJECT_ROOT / p
        if fp.exists():
            try:
                content = fp.read_text(encoding="utf-8", errors="replace")
                # limita a 400 righe per file per non esaurire i token
                lines = content.splitlines()
                if len(lines) > 400:
                    content = "\n".join(lines[:400]) + "\n... (troncato, %d righe totali)" % len(lines)
                parts.append(f"=== {p} ===\n{content}\n=== FINE {p} ===")
            except Exception as e:
                log.warning("lettura %s: %s", p, e)
    return "\n\n".join(parts)


def _parse_response(text):
    """Parsing robusto: prova JSON, poi cerca blocchi marcati."""
    # prova JSON diretto
    text = text.strip()
    # togli markdown code blocks
    if text.startswith("```"):
        lines = text.splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    # cerca blocchi ### FILE: path ... ### END
    pattern = r'###\s*FILE:\s*(.+?)\n(.*?)###\s*END'
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        return [{"path": m[0].strip(), "content": m[1].strip()} for m in matches]
    # cerca {"path": ..., "content": ...} anche non in lista
    objects = re.findall(r'\{[^{}]*"path"\s*:\s*"([^"]+)"[^{}]*"content"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
    if objects:
        return [{"path": p, "content": c.replace("\\n", "\n").replace('\\"', '"')} for p, c in objects]
    log.warning("codegen: impossibile parsare risposta LLM (%d chars)", len(text))
    return []


def generate_fix(request, relevant_files=None):
    """Chiama il LLM per generare fix reali.

    Args:
        request: descrizione della modifica richiesta
        relevant_files: lista di file da fornire come contesto (opzionale)

    Returns:
        list of {"path": str, "content": str} o lista vuota se fallisce
    """
    key = _api_key()
    if not key:
        log.warning("codegen: GROQ_API_KEY assente")
        return []

    # seleziona file rilevanti
    if not relevant_files:
        relevant_files = _pick_relevant_files(request)

    context = _read_files(relevant_files)
    if not context:
        log.warning("codegen: nessun file leggibile da %s", relevant_files)
        return []

    log.info("codegen: richiesta=%s, files=%s, context_len=%d", request, relevant_files, len(context))

    user_msg = "RICHIEDI: %s\n\nFILE ATTUALI:\n%s" % (request, context)

    for model in MODELS:
        url = "%s/%s:generateContent?key=%s" % (GEMINI_BASE, model, key)
        payload = {
            "contents": [{"role": "user", "parts": [{"text": user_msg}]}],
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "generationConfig": {
                "maxOutputTokens": 16384,
                "temperature": 0.2,
            },
        }
        for attempt in range(3):
            try:
                resp = requests.post(url, json=payload, timeout=120)
                if resp.status_code in (503, 504, 502, 429):
                    log.warning("codegen %s HTTP %s (tentativo %d)", model, resp.status_code, attempt + 1)
                    time.sleep(5 * (attempt + 1))
                    continue
                break
            except Exception as e:
                log.warning("codegen %s attempt %d: %s", model, attempt, e)
                time.sleep(3)
        else:
            continue
        if resp.status_code != 200:
            log.warning("codegen %s HTTP %s: %s", model, resp.status_code, resp.text[:300])
            continue
        data = resp.json()
        text = ""
        candidates = data.get("candidates") or []
        if candidates and isinstance(candidates[0], dict):
            parts = candidates[0].get("content", {}).get("parts", [])
            text = parts[0].get("text", "") if parts else ""
        if not text:
            log.warning("codegen %s: risposta vuota", model)
            continue
        changes = _parse_response(text)
        if changes:
            log.info("codegen: %s ha generato %d modifiche con %s", request, len(changes), model)
            return changes
        log.warning("codegen %s: risposta non parsabile, preview: %s", model, text[:300])
    log.warning("codegen: nessun modello ha prodotto modifiche valide")
    return []


def _pick_relevant_files(request):
    """Seleziona i file più rilevanti in base alla richiesta."""
    req = request.lower()
    mapping = {
        "style": ["app/web/static/style.css", "app/web/static/index.html"],
        "css": ["app/web/static/style.css", "app/web/static/index.html"],
        "design": ["app/web/static/style.css", "app/web/static/index.html", "app/web/static/app.js"],
        "html": ["app/web/static/index.html"],
        "js": ["app/web/static/app.js"],
        "javascript": ["app/web/static/app.js"],
        "bot": ["app/telegram.py"],
        "telegram": ["app/telegram.py"],
        "manifest": ["app/web/static/manifest.json"],
        "pwa": ["app/web/static/manifest.json", "app/web/static/sw.js"],
        "service worker": ["app/web/static/sw.js"],
        "sw": ["app/web/static/sw.js"],
        "logo": ["app/web/static/logo.svg"],
        "favicon": ["app/web/static/favicon.svg"],
        "config": ["config.py"],
        "maintenance": ["app/maintenance.py"],
    }
    for keyword, files in mapping.items():
        if keyword in req:
            return files
    # default: i file più modificati
    return ["app/web/static/style.css", "app/web/static/index.html", "app/web/static/app.js"]
