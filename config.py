"""Configurazione globale del progetto."""
import os

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.abspath(os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data")))
LOG_DIR = os.path.join(BASE_DIR, "logs")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
WIN_PHOTO = os.path.join(ASSETS_DIR, "win.jpg")   # foto notifiche pronostici
STATE_FILE = os.path.join(DATA_DIR, "state.json")
MANUAL_ODDS_FILE = os.path.join(DATA_DIR, "manual_odds.json")
COACHES_FILE = os.path.join(DATA_DIR, "coaches.json")   # registro allenatori
LEARNING_FILE = os.path.join(DATA_DIR, "learning.json")
FOLLOWS_FILE = os.path.join(DATA_DIR, "follows.json")
STARTED_FILE = os.path.join(DATA_DIR, "started.json")   # chat che hanno fatto /start
SUBS_FILE = os.path.join(DATA_DIR, "subs.json")          # abbonamenti ⭐ completi

TOURNAMENT_ID = 23                      # Serie A su Sofascore
STATUS_SEASON_PREFIX = "26/27"          # stagione corrente (Serie A 26/27)

UPDATE_INTERVAL_SECONDS = int(os.environ.get("UPDATE_INTERVAL_SECONDS",
                                              "600"))    # refresh quote/dati ogni 10 min
LIVE_POLL_SECONDS = 30                  # refresh risultati live (super rapido)
WEB_REFRESH_MS = 30000                  # refresh del browser
WEB_LIVE_REFRESH_MS = 10000             # refresh live nel browser
HTTP_TIMEOUT = 25
HTTP_RETRIES = 3
POLITE_DELAY = 0.6                      # secondi tra richieste Sofascore

LAST_RESULTS_N = 10                     # almeno 10 risultati antecedenti
FORM_WINDOW = 5

# Soglie "errore di quota"
ODD_ERROR_MIN_SPREAD = 0.15             # disallineamento relativo minimo (15%)
ODD_MOVE_MIN_PCT = 0.12                 # variazione quota tra snapshot (12%)
ARB_MARGIN = 0.04                       # margine per considerarlo arbitraggio

# Soglie pronostico
VALUE_RELATIVE_EDGE = 0.15              # vantaggio model vs *frazione* minima
MIN_ODD_TO_BET = 1.45
# Il modello NON gioca solo "per valore" su quote assurde: consiglia un esito
# solo se è davvero il suo pronostico (probabilità abbastanza alta) e se la
# quota non è irrealistica. PICK_MAX_ODD è il "cap" sopra il quale non si
# consiglia la giocata anche se l'edge calcolato sembrerebbe alto.
PICK_MIN_PROB = 0.45                    # probabilità minima per consigliare un esito
PICK_MAX_ODD = 2.60                     # quota massima per una giocata consigliata

# Regolarizzazione Bayesian: il campione a inizio stagione è minuscolo (2-4
# giornate) e produce attacco/difesa estremi. Ogni squadra "gioca" anche
# REGULARIZATION_PRIOR partite virtuali a livello di media del campionato.
REGULARIZATION_PRIOR = 3.0

# Blend col mercato e coi pronosticatori esterni (tipster):
#   probs_finali = (1-wM-wT)*modello + wM*mercato + wT*tipster
MARKET_BLEND_WEIGHT = 0.25              # quanto pesa la probabilità implicita delle quote
TIPSTER_BLEND_WEIGHT = 0.10             # quanto pesano le fonti esterne "tipster"
EXACT_SCORE_TOP = 3                     # risultati esatti più probabili da mostrare

# ---- Modello del mercato ("odds come feature", paper arXiv:1710.02824)
# Il consenso de-juicato delle quote non è la probabilità vera: tende a
# sopravvalutare i favoriti. MARKET_MODEL apprende un esponente "alpha" per
# mercato che minimizza il Brier out-of-sample sui pronostici storici e lo
# applica alle quote prima del blend.
MARKET_MODEL_ENABLED = os.environ.get("MARKET_MODEL_ENABLED", "1") != "0"
MARKET_ALPHA_FILE = os.path.join(DATA_DIR, "market_alpha.json")

# ---- Dixon-Coles: correzione dei bassi punteggi (Dixon & Coles 1997)
# Il Poisson indipendente sottostima 0-0 e 1-1 e sovrastima 1-0/0-1. La
# correzione tau di Dixon-Coles ritara le probabilità di quelle 4 celle con
# un singolo parametro rho (negativo: sposta gol dai pareggi bassi ai
# singoli 1-0/0-1... rho<0 rende 0-0/1-1 piu probabili, 1-0/0-1 meno).
# rho=-0.13 e il valore classico usato dai modelli open source.
DIXON_COLES_ENABLED = os.environ.get("DIXON_COLES_ENABLED", "1") != "0"
DIXON_COLES_RHO = float(os.environ.get("DIXON_COLES_RHO", "-0.13"))

# ---- Split casa/trasferta per attacco e difesa
# Le valutazioni di base (attacco/difesa) usano i totali in classifica. Se
# una squadra gioca in casa le sue ultime score a casa contano più di quelle
# generali: pesiamo i numeri casalinghi/esterni col peso
# HOME_AWAY_SPLIT_WEIGHT quando il campione è disponibile.
HOME_AWAY_SPLIT_WEIGHT = float(os.environ.get("HOME_AWAY_SPLIT_WEIGHT", "0.5"))

# ---- Recency decay nella forma: le ultime 5 partite non pesano tutte uguale
# (l'ultima importa di più). FORM_RECENCY_DECAY in (0,1): 1 = nessun peso.
FORM_RECENCY_DECAY = float(os.environ.get("FORM_RECENCY_DECAY", "0.85"))

# Autocritica / apprendimento del modello
TRACKING_MIN_SAMPLES = 5                # campioni minimi prima di correggere un esito
MAX_TRACKED = 400                       # pronostici conservati nello storico
CALIBRATION_CLAMP_LO = 0.55             # correttore minimo applicabile (0.55 = -45%)
CALIBRATION_CLAMP_HI = 1.45             # correttore massimo applicabile (1.45 = +45%)

# Minimo trascorso dal fischio d'inizio prima di interrogare l'esito di una
# partita (backstop). La valutazione "a fine partita" immediata (~30s) avviene
# tramite il monitor live: questa è solo la rete di sicurezza per quando la
# partita non era in diretta (app spenta / avvio successivo).
TRACKING_EVAL_DELAY_HOURS = float(os.environ.get("TRACKING_EVAL_DELAY_HOURS", "2.5"))

# Schedina della giornata: un esito per ogni partita del turno; quante
# giornate archiviate nel registro storico.
SCHEDINA_MAX_HISTORY = 12
SCHEDINA_MIN_PROB = 0.50               # probabilità minima per entrare in schedina
MATCHDAY_WINDOW = 4 * 86400            # durata di una giornata (~96h, ven-lun)
MATCHDAY_SPACING = 7 * 86400           # intervallo tra primi kickoff di turni consecutivi

# Alert "pronto per il 2.5": media mobile degli ultimi N pronostici O/U 2.5
# valutati (over o under, l'esito suggerito dal modello). Quando la
# percentuale di centratura della finestra supera O2_ALERT_TARGET si invia
# una notifica Telegram al proprietario (@ziosapi).
OU_ALERT_TARGET = 0.85                  # 85% = soglia per l'alert
OU_ALERT_WINDOW = 20                    # ultimi N pronostici O/U valutati
OU_ALERT_FILE = os.path.join(DATA_DIR, "ou_alert.json")

# Peso della forza dell'avversario nel modello Poisson: più è alto, più
# vincere/pareggiare contro una squadra forte conta. Misura quanta parte del
# gol atteso viene corretta in base alla differenza di punti in classifica
# con l'avversario. 0 = disattivato.
OPPONENT_STRENGTH_WEIGHT = 0.05

# ---- Nuovo allenatore ("new-manager bounce")
# Rilevamento ibrido: registro manuale in data/coaches.json + auto-detezione
# dal campo `manager` dell'endpoint Sofascore team/{id} (cache quotidiana).
# QUANDO una squadra ha un allenatore in carica da meno di
# NEW_MANAGER_WINDOW_DAYS, il suo gol atteso sale (×NEW_MANAGER_ATTACK_MULT)
# e quello dell'avversario scende (×NEW_MANAGER_DEFENSE_MULT); il morale
# pre-partita riceve NEW_MANAGER_MORALE_BONUS.
NEW_MANAGER_ENABLED = True
NEW_MANAGER_WINDOW_DAYS = 30            # giorni in cui vale "nuova era"
NEW_MANAGER_ATTACK_MULT = 1.15          # λ della squadra riorganizzata
NEW_MANAGER_DEFENSE_MULT = 0.97         # λ dell'avversario (assetto difensivo)
NEW_MANAGER_MORALE_BONUS = 0.8          # punti morale pre-partita
COACH_AUTO_TTL = 86400                  # 1 rilevazione manager al giorno/squadra

# Tor / proxy rotativo per aggirare i blocchi IP di Sofascore (HTTP 403).
# Se impostato e la connessione diretta viene bloccata, il client riprova
# la richiesta attraverso questo proxy (SOCKS).
# In Docker il target diventa "tor" (il servizio compose), non 127.0.0.1.
# Modo rete del client Sofascore: "always" (sempre via Tor, default locale),
# "auto" (parte diretto, passa a Tor solo su blocco), "never" (solo diretto).
# Su Render i nodi Tor escono su IP 403 da Sofascore: prova "auto"/"never".
SOFASCORE_TOR_MODE = os.environ.get("SOFASCORE_TOR_MODE", "always")
TOR_SOCKS_PROXY = os.environ.get("TOR_SOCKS_PROXY", "socks5h://127.0.0.1:9050")
# Porta di controllo Tor per ordinare il cambio identità (NEWNYM).
# username/password: lascia "" se usi solo il cookie di autenticazione.
TOR_CONTROL_HOST = os.environ.get("TOR_CONTROL_HOST", "127.0.0.1")
TOR_CONTROL_PORT = int(os.environ.get("TOR_CONTROL_PORT", "9051"))
TOR_CONTROL_PASSWORD = ""
# Ad ogni blocco 403 proviamo: (1) torza identità Tor nuova, (2) retry.
TOR_FAILOVER_ON_BLOCK = True
# Numero massimo di richieste prima di forzare un nuovo circuito Tor,
# per non riutilizzare sempre lo stesso IP d'uscita.
TOR_ROTATE_EVERY = 25
# Quanti tentativi via Tor proviamo (con cambio circuito) prima di rinunciare:
# alcuni nodi d'uscita sono bloccati da Sofascore, serve provarne diversi.
TOR_MAX_RETRIES = 8

ASSETS_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

SOFASCORE_BASE = "https://www.sofascore.com/api/v1"

# ---- fonti dati
# Ordine del fallback a catena (virgole separate). Capacità per fonte:
#   sofascore : tutto (quote 1X2, h2h, lineups, statistiche, incidenti…).
#               BLOCCATA da Render (HTTP 403): se presente, ogni chiamata
#               analitica resta in retry Tor e il ciclo non completa.
#   espn      : stagione, classifica, risultati, partite, live, quote 1X2
#               (Bet365) + forma/h2h da calendario squadre. Risponde da Render.
DATA_SOURCE_ORDER = [s.strip() for s in os.environ.get(
    "DATA_SOURCE_ORDER", "espn,sofascore").split(",") if s.strip()]
# Sofascore è bloccato (403) da IP datacenter/Render e ogni sua chiamata
# resta in retry Tor blocando il ciclo: escluso per sempre, anche se l'env
# lo riconfigura. Solo il motore ESPN (che risponde 200) viene usato.
DATA_SOURCE_ORDER = [s for s in DATA_SOURCE_ORDER if s != "sofascore"]

ODDSPORTAL_SERIEA_URL = "https://www.oddsportal.com/it/football/italy/serie-a/"
CENTROQUOTE_SERIEA_URL = "https://www.centroquote.it/football/italy/serie-a/"
SOGOSPORT_SERIEA_URL = "https://www.sogosport.com/calcio/italia/serie-a/"
SISAL_SERIEA_URL = "https://www.sisal.it/scommesse/calcio/italia/serie-a"
SNAI_SERIEA_URL = "https://www.snai.it/sport/calcio/serie-a/"

# ---- Tipster esterno: Soccervista (API JSON pubblica)
# Il modello di Soccervista pubblica per ogni partita: esito 1X2, Over/Under
# 2.5, risultato esatto e un punteggio di confidenza (1-10). Usiamo la loro
# API interna, registriamo la loro affidabilità (chi sbaglia viene pesato
# meno o escluso) e fondiamo le previsioni con le nostre.
SV_API_ORIGIN = "https://www.soccervista.com"
SV_SERIE_A_PATH = "/events/by/tournament/COuk57Ci/"   # templateId Serie A
SV_MAX_DAYS = 10                         # orizzonte partite considerate
TIPSTERS_FILE = os.path.join(DATA_DIR, "tipsters.json")
TIPSTER_MIN_SAMPLES = 5                  # campioni minimi prima di "fidarsi"
TIPSTER_MIN_ACCURACY = 0.55              # sotto questa centratura escludo la fonte
TIPSTER_BASE_CONF = 0.62                 # pseudo-prob base per il pick del tipster
TIPSTER_CONF_PER_POINT = 0.04            # aggiunta per punto di confidenza (1-10)

# Persistenza remota (opzionale): con REDIS_URL (es. Upstash Redis free) i file
# importanti (state/learning/follows/started/manual_odds/subs/tipsters) vengono
# salvati anche in Redis: indispensabile su Render/Koyeb free, dove i filesystem
# è effimero.
REDIS_URL = os.environ.get("REDIS_URL", "")

# Porta HTTP: Render inietta PORT; locale usa DEFAULT_PORT.
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = int(os.environ.get("PORT") or "8765")

# Bot Telegram: token da @BotFather (lasciare vuoto per disabilitare).
# TELEGRAM_ALLOWED_IDS = lista di chat_id autorizzati; vuota = tutti.
# In env può essere una stringa "id1,id2,...".
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ALLOWED_IDS = [int(x.strip()) for x in
                        os.environ.get("TELEGRAM_ALLOWED_IDS", "").split(",")
                        if x.strip().isdigit()]

# Proprietario del bot ("il capo"): ha TUTTO gratis, senza abbonamento.
# In ambiente va impostato al chat_id del boss (es. TELEGRAM_OWNER_IDS=1694501243).
TELEGRAM_OWNER_IDS = [int(x.strip()) for x in
                      os.environ.get("TELEGRAM_OWNER_IDS", "").split(",")
                      if x.strip().isdigit()]

# Abbonamento "completo" in Telegram Stars:
#   - gratis: 1 pronostico al giorno
#   - completo: 50 ⭐ / 7 giorni  oppure  100 ⭐ / 30 giorni
SUBS_WEEK_STARS = int(os.environ.get("SUBS_WEEK_STARS", "50"))
SUBS_MONTH_STARS = int(os.environ.get("SUBS_MONTH_STARS", "100"))

# Codici voucher: chi li scrive in chat (o /coupon CODICE) riceve il completo
# "a vita". In ambiente (lista separata da virgole); default vuoto = nessuno.
SUBS_COUPONS = [x.strip() for x in
                os.environ.get("SUBS_COUPONS", "").split(",")
                if x.strip()]