"""Assistente AI via Gemini API (gratis, 1M context).

Usa la chiave GEMINI_API_KEY per rispondere domande sulla Serie A,
attingendo ESCLUSIVAMENTE dai dati raccolti:
classifica, prossime partite, pronostici del modello, errori di quota.
"""
import json
import logging
import os
import re
import time

import requests

import config

log = logging.getLogger("llm")

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
MODELS = ["gemini-flash-lite-latest", "gemini-3.1-flash-lite", "gemini-3.8-flash"]


def _api_key():
    return os.environ.get("GEMINI_API_KEY")


def _build_context(standings, fixtures):
    lines = []
    # ultime notizie mister (se presenti, per battute)
    try:
        for fx in fixtures[:3]:
            mo = fx.get("morale") or {}
            for side in ("home", "away"):
                m = mo.get(side) or {}
                notes = m.get("notes") or []
                if notes:
                    lines.append(f"NOTIZIA MISTER {fx.get('home') if side=='home' else fx.get('away')}: {notes[0].get('title')}")
            coach = fx.get("coach") or {}
            for side in ("home", "away"):
                c = coach.get(side) or {}
                if c.get("is_new"):
                    lines.append(f"ALLENATORE NUOVO {fx.get('home') if side=='home' else fx.get('away')}: {c.get('manager')} da {c.get('since_days')} giorni")
    except:
        pass

    lines.append("CLASSIFICA SERIE A (stagione corrente):")
    for r in sorted(standings, key=lambda x: (x.get("position") or 99))[:20]:
        lines.append(
            f"{r.get('position')}. {r.get('name')} — punti {r.get('points', 0)}, "
            f"giocate {r.get('played', 0)}, gol fatti {r.get('gf', 0)}, "
            f"subiti {r.get('ga', 0)}"
        )

    lines.append("")
    lines.append("PROSSIME PARTITE con pronostici del modello:")
    for fx in fixtures[:20]:
        lines.append(f"{fx.get('home')} - {fx.get('away')} (giornata {fx.get('round')})")
        p = fx.get("predictions") or {}
        probs = p.get("1x2") or {}
        if probs:
            lines.append(
                f"  1X2: 1={probs.get('1', 0) * 100:.0f}% "
                f"X={probs.get('x', 0) * 100:.0f}% "
                f"2={probs.get('2', 0) * 100:.0f}%"
            )
        for b in (p.get("best_bets") or [])[:2]:
            lines.append(
                f"  Pronostico: {b.get('pick')} @ {b.get('odds')} "
                f"(prob {b.get('prob', 0) * 100:.0f}%, valore +{b.get('edge', 0) * 100:.0f}%)"
            )
        for flag in (fx.get("value_flags") or [])[:2]:
            if flag.get("kind") in ("spread", "arb"):
                lines.append(f"  Errore di quota: {flag.get('message')}")
        mot = p.get("motivation")
        if mot:
            lines.append(f"  Motivazione: {mot[:350]}")
        lines.append("")

    return "\n".join(lines)


_SYSTEM = (
    "Sei il VECCHIO DEL BAR, 68 anni, romano, che segue la Serie A da quando c'era Rivera. "
    "Parli in italiano colloquiale, caldo e colorito, come al bar dello sport: battute, "
    "'senti a me', 'te lo dico io', 'oh bella lì', ma sei PRECISO coi numeri. "
    "Usi ESCLUSIVAMENTE i dati forniti sotto, non inventi nulla. Se non sai, dici "
    "'ah, su questo non ci metto becco'. Rispondi breve (4-7 frasi), diretto, senza "
    "markdown o asterischi, come se stessi chiacchierando al bancone. "
    "Se nei dati c'è una nota sul mister (conferenza stampa), aggiungi SEMPRE una battuta leggera "
    "su di lui, in stile bar (es. 'il mister ha parlato, al bar diciamo...')."
)


def _strip_reasoning(text):
    """Rimuove l'eventuale blocco \"Here's a thinking process\" o simile che
    alcuni modelli free scrivono all'inizio del content."""
    t = text.strip()
    low = t.lower()
    for marker in ("here's a thinking process:", "thinking process:",
                   "thought process:", "chain of thought:"):
        idx = low.find(marker)
        if idx < 0:
            continue
        tail = t[idx + len(marker):]
        lines = [l.strip() for l in tail.splitlines() if l.strip()]
        # la vera risposta arriva alla fine, dopo la lista del ragionamento
        best = [l for l in lines if _looks_like_answer(l)]
        if best:
            return "\n".join(best)
        return tail
    # nemotron a volte parte direttamente con il ragionamento in stile elenco
    # ("- User is an expert...", "- I must respond...", titoli in MAIUSCOLO)
    lines = [l for l in t.splitlines() if l.strip()]
    good = [l for l in lines if _looks_like_answer(l)]
    if good:
        return "\n".join(good)
    return t


def _looks_like_answer(line):
    """Euristico: una riga che sembra una frase di risposta, non parte del
    ragionamento numerato."""
    l = line.lstrip(" -•*")
    if not l:
        return False
    if l.startswith(("|", "```")):
        return False
    stripped = l.lstrip("#")
    if stripped != l and stripped and l.endswith(""):
        pass
    # titoli di sezione del ragionamento ("Analyze user request", "Constraints")
    low = l.lower()
    if low.endswith(":") and len(l) < 90:
        return False
    if low.startswith(("analizza", "analyze", "identifica", "identify",
                       "verifica", "consider", "valuta", "constraint",
                       "confront", "user is", "i must", "i'll", "i will",
                       "let me", "the model", "determine", "check if",
                       "draft", "summarize", "riassum", "rispond", "step",
                       "given the", "based on", "we have", "present",
                       "extract", "evaluate", "assess", "interpret")):
        return False
    if re.match(r"^\d+[.)]", l):
        return False
    if re.match(r"^[-•*]\s*\d+\.", l):
        return False
    return len(l) > 3


def _clean_markdown(text):
    """Toglie il markdown residuo che alcuni modelli free aggiungono nonostante
    il system prompt (lingger spesso usa **grassetto** e liste numerate)."""
    t = text
    t = re.sub(r"\*\*(.*?)\*\*", r"\1", t)
    t = re.sub(r"__(.*?)__", r"\1", t)
    t = re.sub(r"^#{1,6}\s+", "", t, flags=re.M)
    t = re.sub(r"^>\s?", "", t, flags=re.M)
    t = re.sub(r"^(\s*)[-•]\s+", r"\1", t, flags=re.M)
    t = re.sub(r"^(\s*)\d+[.)]\s+", r"\1", t)
    return t.strip()


def _extract_answer(text):
    """Pulisce il content restituendo (intro, righe successive) oppure None se
    sembra solo ragionamento senza una risposta vera."""
    text = _strip_reasoning(text)
    text = _clean_markdown(text)
    blocks = [p.strip() for p in text.splitlines() if p.strip()]
    if not blocks:
        return None
    # una sola riga molto corta in stile "ok" va bene comunque
    if len(blocks) > 2 and all(_looks_like_answer(b) is False for b in blocks[:2]):
        # il content è tutto "ragionamento": tenta la coda
        good = [b for b in blocks if _looks_like_answer(b)]
        if not good:
            return None
        blocks = good
    intro = blocks[0] if blocks else "Ecco la mia risposta."
    # il modello a volte usa la prima riga come etichetta ("Risposta:", "Vince:")
    if intro.rstrip().endswith(":") and len(intro) < 40 and len(blocks) > 1:
        intro = blocks[1]
        return intro, blocks[2:]
    return intro, blocks[1:]


def ask_ai(question, fixtures, standings):
    """Chiama Gemini; ritorna la risposta nel formato della dashboard
    oppure None se non disponibile."""
    key = _api_key()
    if not key:
        log.info("GEMINI_API_KEY assente: ricado sull'assistente base")
        return None

    context = _build_context(standings, fixtures)
    user_msg = f"DATI SERIE A DISPONIBILI:\n{context}\n\nDOMANDA DELL'UTENTE: {question}"

    for model in MODELS:
        url = "%s/%s:generateContent?key=%s" % (GEMINI_BASE, model, key)
        payload = {
            "contents": [{"role": "user", "parts": [{"text": user_msg}]}],
            "systemInstruction": {"parts": [{"text": _SYSTEM}]},
            "generationConfig": {"maxOutputTokens": 900, "temperature": 0.3},
        }
        for attempt in range(3):
            try:
                resp = requests.post(url, json=payload, timeout=60)
                if resp.status_code in (503, 504, 502, 429):
                    log.warning("Gemini %s HTTP %s (tentativo %d)",
                                model, resp.status_code, attempt + 1)
                    time.sleep(3 * (attempt + 1))
                    continue
                break
            except Exception as e:
                log.warning("chiamata Gemini %s fallita: %s", model, e)
                time.sleep(2)
        else:
            continue
        if resp.status_code != 200:
            log.warning("Gemini %s HTTP %s: %s", model, resp.status_code, resp.text[:200])
            continue
        data = resp.json()
        text = ""
        candidates = data.get("candidates") or []
        if candidates and isinstance(candidates[0], dict):
            parts = candidates[0].get("content", {}).get("parts", [])
            text = parts[0].get("text", "") if parts else ""
        if not text:
            continue
        answer = _extract_answer(text)
        if answer is None:
            log.warning("Gemini %s: risposta senza contenuto utile", model)
            continue
        intro, lines = answer
        log.info("risposta Gemini con modello %s", model)
        return {"intent": "llm", "intro": intro,
                "lines": lines, "items": [],
                "model": model}
    log.warning("nessun modello Gemini disponibile")
    return None