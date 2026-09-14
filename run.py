"""Avvio di Serie A Stats.

Esempi:
  ./run.py --once          # un solo ciclo di raccolta dati
  ./run.py                 # server web + aggiornamento ogni 10 min
  ./run.py --port 8899     # porta personalizzata
  ./run.py --tunnel        # apre anche un tunnel cloudflared (se installato)
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from app.core.store import Store
from app.core.tunnel import Tunnel
from app.scheduler import Scheduler
from app.scheduler import run_cycle
from app.web.server import create_app


def setup_logging(verbose=False):
    os.makedirs(config.LOG_DIR, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(os.path.join(config.LOG_DIR, "app.log"), encoding="utf-8"),
        ],
    )


def start_heartbeat(url):
    """Ping periodico del proprio URL pubblico (es. Koyeb) per evitare che la
    piattaforma porti l'istanza free in sleep dopo ~1h senza traffico."""
    import threading
    import time
    import urllib.request

    log = logging.getLogger("heartbeat")
    interval = int(os.environ.get("HEARTBEAT_INTERVAL_SECONDS", "1500"))

    def _ping():
        while True:
            time.sleep(interval)
            try:
                with urllib.request.urlopen(url + "/healthz", timeout=20) as r:
                    log.info("heartbeat OK (%s)", r.status)
            except Exception as e:
                log.warning("heartbeat fallito: %s", e)

    log.info("heartbeat su %s ogni %ds", url, interval)
    threading.Thread(target=_ping, daemon=True, name="heartbeat").start()


def main():
    parser = argparse.ArgumentParser(description="Serie A Stats")
    parser.add_argument("--once", action="store_true",
                        help="esegue un singolo ciclo di raccolta e termina")
    parser.add_argument("--host", default=config.DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=config.DEFAULT_PORT)
    parser.add_argument("--no-scheduler", action="store_true",
                        help="avvia solo il server web senza raccolta")
    parser.add_argument("--tunnel", action="store_true", default=True,
                        help="apre un tunnel cloudflared per accedere da Safari fuori rete")
    parser.add_argument("--no-tunnel", dest="tunnel", action="store_false",
                        help="disabilita il tunnel pubblico")
    parser.add_argument("--telegram", action="store_true", default=True,
                        help="avvia il bot Telegram insieme al server")
    parser.add_argument("--no-telegram", dest="telegram", action="store_false",
                        help="disabilita il bot Telegram")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    # Interruttore operativo: se ENABLE_SCHEDULER=1 sovrascrive il default
    # --no-scheduler del container (per attivare la raccolta su Render).
    if os.environ.get("ENABLE_SCHEDULER", "").lower() in ("1", "true", "yes"):
        args.no_scheduler = False

    setup_logging(args.verbose)

    store = Store()
    store.load()
    store.set("code", "espn-2026-form")
    store.save()

    if args.once:
        run_cycle(store, quick=False)
        print("\nStato salvato in", config.STATE_FILE)
        return

    scheduler = None
    if not args.no_scheduler:
        scheduler = Scheduler(store).start()

    live_monitor = None
    if not args.once and not args.no_scheduler:
        from app.live import LiveMonitor
        live_monitor = LiveMonitor(store).start()

    import threading
    from app.telegram import TelegramBot
    if args.telegram and config.TELEGRAM_BOT_TOKEN:
        bot = TelegramBot(store)
        threading.Thread(target=bot.start, name="telegram", daemon=True).start()
    else:
        bot = None

    tunnel = Tunnel(args.port, config.DATA_DIR)

    if os.environ.get("PUBLIC_URL"):
        start_heartbeat(os.environ["PUBLIC_URL"].rstrip("/"))
    else:
        logging.getLogger("heartbeat").info("PUBLIC_URL non impostato: heartbeat disattivato")

    def open_tunnel():
        t = tunnel
        if not t.available:
            print("\n  Link pubblico disattivato: cloudflared non trovato.\n")
            return
        t.start()
        url = __import__("app.core.tunnel", fromlist=["wait_url"]).wait_url(t, timeout=45)
        if url:
            print(f"\n  Link pubblico (Safari da fuori casa):  {url}\n")
        else:
            print("\n  Tunnel in avvio... verificando su /api/tunnel.\n")

    if args.tunnel:
        __import__("threading").Thread(target=open_tunnel, daemon=True).start()

    app = create_app(store, tunnel)

    host = "0.0.0.0"
    print(f"\nSerie A Stats avviato:")
    print(f"  Dashboard web:   http://localhost:{args.port}   (o http://<IP-macchina>:{args.port})")
    print(f"  Aggiornamento:   ogni {config.UPDATE_INTERVAL_SECONDS // 60} minuti")
    if scheduler:
        print("  Raccolta dati:   in esecuzione in background")
    if live_monitor:
        print(f"  Risultati live:  ogni {config.LIVE_POLL_SECONDS} secondi")
    if bot:
        print("  Bot Telegram:    attivo")
    if args.tunnel and tunnel.available:
        print("  Link pubblico:   in preparazione (lo trovi anche nel footer della dashboard)")
    print()
    app.run(host=host, port=args.port, threaded=True, debug=False)


if __name__ == "__main__":
    main()