"""Mimo v2.5 Free — agente QA tester accanito (24/7).

Simula un utente arrabbiato che testa continuamente il sistema:
- Pinga le API per verificare che rispondano
- Controlla che i dati siano presenti e sensati
- Segnala problemi in data/mimo_complaints.json
- Notifica su Telegram quando trova bug gravi

BigPickle e MuseSpark leggono le sue lamentele al risveglio.
"""
import json
import logging
import os
import time
import threading
import random

import requests

import config
from app.core import kv

log = logging.getLogger("mimo_agent")

COMPLAINTS_FILE = "mimo_complaints.json"
BASE_URL = os.environ.get("APP_URL", "http://localhost:5000")

# frasi da utente arrabbiato
RAGE_INTROS = [
    "MA CHE CAZZO?!",
    "ASPETTA UN PO'...",
    "MA SERIAMENTE?!",
    "OH, QUESTO NON VA!",
    "CHE SCHIFO!",
    "MA CHI L'HA FATTA CODA?!",
    "MA È POSSIBILE?!",
    "NO NO NO, QUESTO NON LO ACCETTO!",
    "QUALCUNO MI SPIEGA?!",
    "MA CHI CONTROLLA 'STE COSE?!",
]

# frasi di lamentele per tipo di problema
COMPLAINT_TEMPLATES = {
    "api_down": [
        "L'API {endpoint} non risponde! HTTP {status}",
        "Provato {endpoint} → timeout o errore {status}. Che roba è?!",
        "Ma {endpoint} è morto? Risposta: {status}",
    ],
    "empty_data": [
        "{endpoint} torna vuoto! Nessun dato!",
        "Ma {endpoint} non ha dati! Tutto null!",
        "Le partite sono sparite da {endpoint}!",
    ],
    "stale_data": [
        "I dati di {endpoint} sembrano vecchi di {age} minuti!",
        "Ma le stats sono ferme? Ultimo aggiornamento {age} minuti fa!",
        "DAI, i dati dovrebbero aggiornarsi ogni 10 min! Sono passati {age}!",
    ],
    "prediction_wrong": [
        "Il pronostico per {match} era {pred} ma è finito {result}. GRAZIE!",
        "{match}: il modello diceva {pred}, poi è uscito {result}. Bell'uso dei miei soldi!",
        "Errore su {match}: {pred} → {result}. Ma che pronostici sono?!",
    ],
    "slow_response": [
        "{endpoint} ci ha messo {time}s! Ma siamo al Barilla?!",
        "Risposta lenta: {endpoint} in {time}s. L'utente se ne va!",
        "ATTENZIONE: {endpoint} risponde in {time}s, troppo lento!",
    ],
    "missing_feature": [
        "Manca {feature}! Ma come si fa?!",
        "Non trovo {feature}! L'utente vuole {feature}!",
        "{feature} non c'è! Degradare l'esperienza!",
    ],
}


def _rage_intro():
    return random.choice(RAGE_INTROS)


def _complaint(template_key, **kwargs):
    tpl = random.choice(COMPLAINT_TEMPLATES[template_key])
    return tpl.format(**kwargs)


def _load_complaints():
    data = kv.read_json(COMPLAINTS_FILE)
    return data if isinstance(data, dict) else {"complaints": [], "stats": {}}


def _save_complaints(data):
    kv.write_json(COMPLAINTS_FILE, data)


def _send_telegram_alert(text):
    """Manda alert su Telegram all'owner."""
    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        return
    targets = list(config.TELEGRAM_OWNER_IDS) if config.TELEGRAM_OWNER_IDS else ["@Ziosapi"]
    for chat_id in targets:
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
        except Exception as e:
            log.warning("mimo telegram alert fallito: %s", e)


def _test_endpoint(endpoint, method="GET", timeout=10):
    """Testa un endpoint e torna (status_code, response_time, data)."""
    url = f"{BASE_URL}{endpoint}"
    try:
        t0 = time.time()
        if method == "GET":
            resp = requests.get(url, timeout=timeout)
        else:
            resp = requests.post(url, timeout=timeout)
        elapsed = round(time.time() - t0, 1)
        try:
            data = resp.json()
        except Exception:
            data = None
        return resp.status_code, elapsed, data
    except requests.exceptions.Timeout:
        return 0, timeout, None
    except Exception as e:
        return -1, 0, str(e)


def _check_fixtures(store):
    """Controlla che le fixtures siano presenti e ragionevoli."""
    complaints = []
    fixtures = store.get("fixtures", [])
    if not fixtures:
        complaints.append({
            "type": "empty_data",
            "message": _complaint("empty_data", endpoint="/fixtures"),
            "severity": "critical",
            "endpoint": "/api/fixtures",
        })
    else:
        for fx in fixtures[:5]:
            if not fx.get("predictions"):
                complaints.append({
                    "type": "missing_feature",
                    "message": _complaint("missing_feature", feature=f"pronostico per {fx.get('home')} vs {fx.get('away')}"),
                    "severity": "low",
                    "endpoint": f"/api/fixtures/{fx.get('id')}",
                })
    return complaints


def _check_standings(store):
    """Controlla che la classifica sia presente."""
    complaints = []
    standings = store.get("standings", [])
    if not standings:
        complaints.append({
            "type": "empty_data",
            "message": _complaint("empty_data", endpoint="/standings"),
            "severity": "critical",
            "endpoint": "/api/standings",
        })
    elif len(standings) < 18:
        complaints.append({
            "type": "empty_data",
            "message": f"Classifica incompleta: solo {len(standings)} squadre su 20!",
            "severity": "high",
            "endpoint": "/api/standings",
        })
    return complaints


def _check_predictions(store):
    """Controlla che i pronostici siano presenti e con valori validi."""
    complaints = []
    fixtures = store.get("fixtures", [])
    missing = 0
    for fx in fixtures:
        p = fx.get("predictions") or {}
        probs = p.get("1x2") or {}
        if not probs:
            missing += 1
        else:
            total = probs.get("1", 0) + probs.get("x", 0) + probs.get("2", 0)
            if abs(total - 1.0) > 0.1:
                complaints.append({
                    "type": "prediction_wrong",
                    "message": f"Probabilità non normalizzate per {fx.get('home')} vs {fx.get('away')}: somma = {total:.2f}",
                    "severity": "high",
                    "endpoint": f"/api/fixtures/{fx.get('id')}",
                })
    if missing > 0 and missing == len(fixtures):
        complaints.append({
            "type": "empty_data",
            "message": _complaint("empty_data", endpoint="tutti i pronostici"),
            "severity": "critical",
            "endpoint": "/api/fixtures",
        })
    elif missing > 3:
        complaints.append({
            "type": "missing_feature",
            "message": f"{missing} partite su {len(fixtures)} senza pronostico!",
            "severity": "high",
            "endpoint": "/api/fixtures",
        })
    return complaints


def _check_api_health():
    """Pinga le API principali e segnala problemi."""
    complaints = []
    endpoints = [
        ("/api/fixtures", "GET"),
        ("/api/standings", "GET"),
        ("/api/ask", "POST"),
    ]
    for ep, method in endpoints:
        status, elapsed, data = _test_endpoint(ep, method, timeout=15)
        if status == 0:
            complaints.append({
                "type": "api_down",
                "message": _complaint("api_down", endpoint=ep, status="timeout"),
                "severity": "critical",
                "endpoint": ep,
            })
        elif status == -1:
            complaints.append({
                "type": "api_down",
                "message": _complaint("api_down", endpoint=ep, status=data or "error"),
                "severity": "critical",
                "endpoint": ep,
            })
        elif status >= 500:
            complaints.append({
                "type": "api_down",
                "message": _complaint("api_down", endpoint=ep, status=status),
                "severity": "critical",
                "endpoint": ep,
            })
        elif elapsed > 10:
            complaints.append({
                "type": "slow_response",
                "message": _complaint("slow_response", endpoint=ep, time=elapsed),
                "severity": "medium",
                "endpoint": ep,
            })
    return complaints


class MimoAgent(threading.Thread):
    """Mimo v2.5 Free — QA tester accanito che gira 24/7."""

    def __init__(self, store):
        super().__init__(daemon=True, name="mimo-qa-10m")
        self.store = store

    def run(self):
        interval = int(os.environ.get("MIMO_INTERVAL", "10")) * 60
        log.info("Mimo v2.5 Free QA agent avviato - primo giro tra 60s, poi ogni %ds", interval)
        try:
            time.sleep(60)
            self.tick()
        except Exception as e:
            log.exception("Mimo primo tick: %s", e)
        while True:
            time.sleep(interval)
            try:
                self.tick()
            except Exception as e:
                log.exception("Mimo tick: %s", e)

    def tick(self):
        log.info("Mimo v2.5 Free: inizio test accaniti...")
        complaints = []

        # test API health
        complaints.extend(_check_api_health())

        # test dati interni
        complaints.extend(_check_fixtures(self.store))
        complaints.extend(_check_standings(self.store))
        complaints.extend(_check_predictions(self.store))

        # salva lamentele
        state = _load_complaints()
        existing_msgs = {c.get("message") for c in state.get("complaints", [])[-50:]}
        new_complaints = []
        for c in complaints:
            c["at"] = int(time.time())
            if c["message"] not in existing_msgs:
                new_complaints.append(c)
                existing_msgs.add(c["message"])

        if new_complaints:
            state["complaints"] = (state.get("complaints") or [])[-100:] + new_complaints
            state["stats"] = {
                "last_run": int(time.time()),
                "total_complaints": len(state["complaints"]),
                "critical": sum(1 for c in state["complaints"] if c.get("severity") == "critical"),
                "high": sum(1 for c in state["complaints"] if c.get("severity") == "high"),
            }
            _save_complaints(state)

            # notifica su telegram solo per critical
            critical = [c for c in new_complaints if c.get("severity") == "critical"]
            if critical:
                msg = f"🔴 Mimo v2.5 Free ha trovato {len(critical)} bug critici!\n\n"
                for c in critical[:3]:
                    msg += f"• {c['message']}\n"
                if len(critical) > 3:
                    msg += f"\n... e altri {len(critical)-3}"
                _send_telegram_alert(msg)

            log.warning("Mimo: %d nuove lamentele (%d critical, %d high)",
                        len(new_complaints),
                        sum(1 for c in new_complaints if c.get("severity") == "critical"),
                        sum(1 for c in new_complaints if c.get("severity") == "high"))
        else:
            log.info("Mimo: tutto ok, nessuna nuova lamentela")
