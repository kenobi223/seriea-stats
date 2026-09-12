# Serie A Stats ⚽

Dashboard web + motore di analisi per le partite di **Serie A**:

- classifica, **ultimi 10 risultati** per squadra e prestazioni della stagione corrente
- **formazioni titolari probabili** (ultimo undici ufficiale) e, a ridosso del fischio,
  quelle confermate
- **arbitro della partita** con media cartellini in carriera e **in stagione**
- statistiche squadra: tiri in porta, cartellini subiti, gol, forma casa/trasferta
- **quote da più fonti**, aggiornate **ogni 10 minuti**
- **risultati delle giornate** della stagione (tab **Risultati e live**,
  comando `/risultati`), aggiornati a ogni ciclo
- **risultati live super rapidi**: monitor dedicato che interroga Sofascore
  **ogni 30 secondi** (`sport/football/events/live` in un'unica richiesta);
  la dashboard li mostra con refresh ogni 10 s comando `/live`
- **notifiche Telegram su richiesta**: con `/segui <squadra>` ricevi avvisi a
  inizio partita, a ogni gol (con marcatore) e a fine gara; `/stopsegui` per
  fermarle
- **🎁 foto "pronostico indovinato" a tutti gli avviati**: quando a fine
  partita un best-bet del modello viene centrato, a chiunque abbia scritto
  almeno una volta `/start` viene inviata `assets/win.jpg` con il risultato
  indovinato, probabilità e quota. La foto parte una sola volta per
  pronostico; chi segue già squadre (`/segui`) viene registrato
  automaticamente.
- **menu Telegram completo e cliccabile**: `/start` apre una tastiera inline
  con ogni funzionalità (classifica, partite, risultati, live, pronostici,
  tiri in porta, tiri giocatori, morale e conferenze, arbitri, errori di
  quota, onestà del modello, segui squadre)
  — niente bisogno di digitare i comandi (che comunque restano validi)
- **donazioni in ⭐ Telegram Stars**: bottone `⭐ Donazioni` nel menu con i
  importi (10–500 stelle), pagamento via fattura XTR senza portafogli esterni
- **lingua italiano / inglese / spagnolo**: bottone `🌐 Lingua` nel menu,
  preferenza salvata per chat (i contenuti dell'assistente AI restano in
  italiano)
- rilevamento **"errori di quota"**: disallineamento tra bookmaker sullo stesso esito
  (es. tiro in porta di Lautaro @1.80 su Sisal vs @2.50 su SNAI → segnalato),
  movimenti di linea tra i refresh, possibili arbitraggi
- **pronostico per ogni partita** con probabilità modello (Poisson), gol attesi e
  motivazione in italiano
- **autocritica e apprendimento**: ogni pronostico viene salvato, confrontato con
  il risultato reale a fine partita, e il modello corregge da solo le proprie
  probabilità in base agli errori (tab **Onestà del modello** + bot `/tracking`):
  tasso di centratura, Brier score, fasce "predetto vs reale" e correttori appresi
- **Assistente AI** (niente chiavi esterne): fai domande in italiano e ottieni consigli
  sui **tiri in porta** (scontati / probabili), errori di quota, pronostici, arbitri
  e analisi partita per partita
- **Link pubblico**: acceso di default, la dashboard è raggiungibile anche **da un
  telefono fuori casa** (Safari su dati mobili) tramite cloudflared

## Requisiti

Linux (testato su CachyOS/Arch, funziona su qualsiasi distro), Python 3.11+.

## Installazione

```bash
cd seriea-stats
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Avvio

```bash
.venv/bin/python run.py                 # dashboard + aggiornamento ogni 10 min
.venv/bin/python run.py --once          # un solo ciclo di raccolta dati
.venv/bin/python run.py --port 8899     # porta personalizzata
.venv/bin/python run.py --no-tunnel     # disabilita il link pubblico di default
```

Apri quindi `http://localhost:8765` (oppure l'indirizzo IP della macchina).
Il **link pubblico** (URL `*.trycloudflare.com`) compare nel terminale all'avvio
e in fondo alla dashboard: lo apri da qualsiasi telefono/PC, anche fuori casa.
Se `cloudflared` manca, scaricalo in `./bin/` (sei libero di installarlo col
gestore pacchetti della tua distro) oppure usa il port forwarding.

### Dashboard: il tab "Chiedi all'AI"

Prova domande come:

- «che tiri in porta mi consigli? non scontati, però probabili»
- «ci sono errori di quota oggi?»
- «qual è il pronostico della giornata?»
- «arbitri con più cartellini»
- «analizza Juventus - AC Milan»

Le risposte sono generate dai dati raccolti (niente chiavi API esterne).

### Accesso da Safari fuori rete

1. **stessa LAN**: apri `http://IP-DEL-PC:8765` (es. `http://192.168.1.8:8765`).
2. **da fuori casa (consigliato)**: il link pubblico `*.trycloudflare.com` è attivo di
   default — lo trovi nel terminale all'avvio e nel **footer della dashboard** (tab
   qualunque). Aprilo da qualsiasi telefono, anche su rete dati. Il link cambia ogni
   riavvio del programma. In alternativa: apri la porta 8765 nel router (port forwarding)
   verso l'indirizzo IP della macchina.

## Fonti dati

| Fonte | Uso |
|---|---|
| **Sofascore (no chiave)** | calendario, classifica, risultati, statistiche, cartellini, arbitri, infortuni, quote 1X2 e mercati aggiuntivi |
| **centroquote.it** | conferma calendario Serie A (rete italiana) |
| **Sisal / SNAI / Sogosport** | scraper automatico **best-effort**: molti bookmaker bloccano gli IP dei data center; su una rete casalinga vengono rilevati in automatico |
| **Import manuale** | quote di OGNI mercato (inclusi i tiri in porta giocatore) incollate a mano |

### Mercati giocatore (es. "Lautaro tiro in porta")

I comparatori non pubblicano questi mercati. Aggiungili a mano dal tab
**Import quote (Sisal/SNAI)** della dashboard (una voce per bookmaker) o con un CSV:

```csv
casa,trasferta,mercato,esito,bookmaker,quota
Juventus,AC Milan,Tiri in porta,Lautaro Martinez,sisal,1.80
Juventus,AC Milan,Tiri in porta,Lautaro Martinez,snai,2.50
```

```bash
.venv/bin/python scripts/import_odds.py data/quote.csv
```

Non appena due bookmaker hanno lo stesso esito con un disallineamento ≥ 15%,
viene generata la segnalazione **"Errore di quota"** (nel primo esempio: 38,9%).

### Tiri in porta dei giocatori (threat score)

Per ogni prossima partita, la dashboard e il bot (sezione **✨ Tiri giocatori**)
mostrano i migliori tiratori dei due undici probabili, calcolando dagli ultimi
3 match finiti in stagione:

- media **tiri in porta a gara** per giocatore (`totalShots - shotOffTarget` dalle lineup);
- **fair odds** onesti per Over 0.5 / Over 1.5 tiri in porta, dalla distribuzione reale del giocatore;
- **threat score 1-10**: la media, corretta per quanto l'avversario produce
  tiri in porta rispetto alla media della lega → atteso per la partita di oggi;
- **confidenza** 🟢🟡🔴 (in base a partite e minuti) col colore del badge, così non
  vengono gonfiati giocatori visti troppo poche volte.

Sofascore non espone i mercati giocatore gratis: le quote dei bookmaker per
"Tiro in porta di X" vanno aggiunte a mano (vedi sopra), e con calco questi
numeri diventano il confronto onesto.

### Probabili formazioni, infortuni e morale (conferenze dei mister)

- **XI probabile**: per ogni prossima partita la formazione più probabile è
  un **merge di due fonti** — l'XI probabile di Sofascore (vicino al fischio)
  + un predittore interno che pesa gli ultimi undici ufficiali di ogni
  squadra (titolarità e minuti) escludendo infortunati e squalificati. I
  giocatori concordi tra le fonti sono marcati ✔, quelli di una sola fonte
  `sf`/`mod`, e i posti in contesa sono elencati ("In corsa"). Così le
  formazioni ci sono anche a 5-7 giorni dall'inizio (`previsione dati`), con
  badge "confermato / novità" rispetto all'ultimo undici ufficiale e
  formazione confermata ufficiale a ridosso del calcio d'inizio.
- **Infortuni e squalifiche**: per ogni squadra gli assenti della partita
  (`missingPlayers`) con motivo (infortunio muscolare, squalifica...) e data
  di rientro; i tiri-in-porta e i pronostici usano gli undici *senza* questi
  giocatori.
- **🎭 Morale pre/post**: punteggio 1-10 per ogni squadra (punti a gara
  recenti, assenti, forza dell'avversario) + il tono dello spogliatoio dagli
  ultimi titoli delle conferenze del mister (Google News RSS, cached 6h);
  dopo la partita il morale si aggiorna con il risultato (vittoria/scarto/gol/
  porta inviolata) sia nella dashboard sia nel bot.

## Configurazione (`config.py`)

- `UPDATE_INTERVAL_SECONDS = 600` → intervallo refresh quote (i dati partite/cartellini
  non cambiano di giornata e vengono serviti dalla cache)
- `LIVE_POLL_SECONDS = 30` → intervallo polling risultati live (una sola richiesta
  per ciclo, `sport/football/events/live`)
- `ODD_ERROR_MIN_SPREAD = 0.15` → soglia disallineamento tra bookmaker
- `ODD_MOVE_MIN_PCT = 0.12` → soglia movimento di linea tra i refresh
- `VALUE_RELATIVE_EDGE = 0.15` → margine minimo per suggerire una puntata con valore
- `LAST_RESULTS_N = 10` → risultati antecedenti considerati
- `TRACKING_MIN_SAMPLES = 5` → campioni minimi prima che il modello si corregga su un esito
- `CALIBRATION_CLAMP_LO / _HI = 0.55 / 1.45` → limite correttore appreso su una probabilità
- `MAX_TRACKED = 400` → pronostici conservati nello storico per l'autocritica

## Struttura

```
run.py                  avvio (server + scheduler)
config.py               impostazioni e soglie
app/sources/            Sofascore, centroquote, bookmaker, merge quote
app/analysis/           forma, arbitri, TIRI IN PORTA ed errori di quota, assistente, pronostici
app/analysis/tracker.py giudica e corregge il modello (pronostici salvati, centratura, calibrazione)
app/core/               storage e tunnel cloudflared (link pubblico)
app/web/                dashboard Flask + frontend
app/scheduler.py        ciclo di aggiornamento (10 min)
scripts/import_odds.py  import quote manuali da CSV
data/                   stato, cache, storico apprendimento, log tunnel (generato)
```

## Come funziona l'autocritica

Ad ogni ciclo lo strumento:

1. **salva** i pronostici emessi (probabilità 1X2, Over/Under, BTTS e le giocate
   suggerite) in `data/learning.json`, prima che la partita si giochi;
2. **valuta** a partita finita il risultato reale e segna ogni pronostico come
   indovinato o sbagliato;
3. **analizza** dove ha sbagliato: tasso di centratura, Brier score (più basso
   = più onesto), fasce "probabilità dichiarata vs centratura reale" ed errori
   più clamorosi;
4. **corregge** le probabilità dei prossimi pronostici moltiplicandole per un
   fattore appreso (`probabilità reale / probabilità stimata`, clamp amministrato)
   e rinormalizzandole: se il modello era troppo ottimista su un esito, lo
   abbassa.

Vedi i risultati nel tab **Onestà del modello** della dashboard o chiedi al bot
Telegram `/tracking`. La correzione è progressiva: con più risultati valutati il
modello diventa più affidabile e onesto (meno "convinzioni" sbagliate).

## Abbonamento "completo" in Telegram Stars

Il bot monetizza i pronostici con **Telegram Stars** (`sendInvoice`, currency XTR):

- **Gratis**: 1 pronostico al giorno (il miglior pick della giornata, una per
  sezione: pronostici / tiri / tiri giocatori; contatore giornaliero condiviso).
- **⭐ 50 / 1 settimana** oppure **⭐ 100 / 1 mese**: "completo" = TUTTI i
  pronostici della giornata, tiri in porta, tiri dei giocatori.
- **Il capo** (`TELEGRAM_OWNER_IDS`, default `1694501243`) ha tutto gratis:
  nessun abbattimento, badge "👑 Sei il CAPO" nella sezione abbonamento.

Dove guardare:
- Menu → **⭐ Abbonati** → bottone `⭐ 50 · 1 settimana` / `⭐ 100 · 1 mese` → il
  pagamento è una fattura in Stars (niente carta).
- `app/subs.py`: scadenze e contatore giornaliero (persistiti in `kv`, quindi
  sopravvivono su Render), `config.SUBS_WEEK/MONTH_STARS`, `TELEGRAM_OWNER_IDS`.
- `app/telegram.py`: invio fattura (`sub:week`/`sub:month`), `_on_successful_payment`
  attiva/estende l'abbonamento (estende dalla scadenza attuale), gating nelle
  sezioni `pronostici`/`tiri`/`shots` e nei comandi `/pronostici` `/bet` `/tiri`.
- Gating: sezione **💰 Pronostici** e affini, non classifica/live/risultati
  (restano gratuiti).

## Deploy 24/7 gratuito (Oracle Cloud Always Free)

Per tenere il bot sempre attivo senza costi, containerizzo l'app e la mando su
una VM **Oracle Cloud Always Free** (4 OCPU ARM / 24 GB RAM, free per sempre).
Include il container Tor (da cui il bot parte sempre per evitare i 403 di
Sofascore) e il volume dati persistente.

**1. Crea la VM su Oracle Cloud**
- Vai su cloud.oracle.com, attiva il "Always Free" account (chiede una carta
  ma non addebita finché resti sotto le soglie Always Free).
- Crea una VM: **Ubuntu 22.04/24.04**, shape **Ampere A1 (ARM)**, da 4 OCPU/24GB
  (solo soglie Always Free). Salva chiave SSH. Prendi nota dell'IP pubblico.

**2. Prepara il pacchetto (da qui)**
```bash
bash deploy/package.sh            # crea /tmp/seriea-stats.tar.gz
scp /tmp/seriea-stats.tar.gz ubuntu@<IP>:/tmp/
```

**3. Avvia sulla VM**
```bash
ssh ubuntu@<IP>
tar xzf /tmp/seriea-stats.tar.gz -C ~/
cd seriea-stats
bash deploy/setup-oracle.sh        # installa Docker; logout+login, poi ancora
TELEGRAM_BOT_TOKEN=123456:AAAA bash deploy/setup-oracle.sh   # seconda esecuzione
docker compose ps                  # tor + app sempre up (restart=always)
docker compose logs -f app         # log
```
La prima esecuzione installa Docker e chiede di rientrare nella sessione per
usare `docker` senza sudo; la seconda (che può passare `TELEGRAM_BOT_TOKEN`) crea
il `.env`, costruisce e avvia.

**Accesso alla dashboard** — il bot è l'interfaccia principale; la web UI
(porta 8765) è in ascolto solo sulla VM: `ssh -L 8765:127.0.0.1:8765 ubuntu@<IP>`
poi apri `http://127.0.0.1:8765`. (Con `cloudflared` installato sulla VM apre
anche un link pubblico `trycloudflare` come sul server locale.)

**Sicurezza**: metti il token nel `.env` (non nel source); `TELEGRAM_ALLOWED_IDS`
è una lista di chat_id separata da virgole. I dati (`data/`) e `assets/` vivono
sul volume, sopravvivono a `docker compose down`/`up`.

## Deploy "sempre up" su Render free (scelta consigliata)

Render free tier può dormire dopo l'inattività, ma per **questo progetto** il
dormiente è controproducente (bot che fa polling, monitor live, scheduler ogni
~10 min, foto "pronostico indovinato"). Quindi qui non si "scala a zero":
si tiene il servizio **sveglio con un ping gratuito ogni ~9 min** (es.
cron-job.org o UptimeRobot → `https://TUOAPP.onrender.com/healthz`) e si rende
il filesystem effimero indifferente salvando i dati in **Redis free (Upstash)**.

**Architettura**: un solo contenitore (Python + Tor dentro, via `entrypoint.sh`).

1. **Persistenza** — crea un'istanza free su upstash.com (no carta) → copia
   `REDIS_URL`. Senza `REDIS_URL` il progetto continua a usare i file locali
   (non persi su Render ma rigenerati).
2. **Codice su GitHub**: `git init`, push del progetto (senza `data/`) in un
   repo (anche pubblico), collega Render.
3. **Nuovo Web Service** su Render: collegato al repo, `Dockerfile` in root,
   plan **free**, health check path `/healthz`.
4. **Env**: `REDIS_URL` (Upstash) e `TELEGRAM_BOT_TOKEN`. Render inietta
   `PORT` da solo.
5. **Keepalive**: ping ogni ~9 min su `/healthz` (così il processo resta
   sveglio entro le 750h/mese del free tier, i thread di bot/live/scheduler
   girano senza interruzioni).

Utile: `/healthz` risponde `{"ok": true, "updated": ...}`; la dashboard web
resta su `:PORT` (porta assegnata da Render, HTTPS incluso). Il tunnel
`cloudflared` non serve: Render espone già la web.

### Alternativa: Oracle Cloud Always Free (VM propria, Tor in contenitore separato)

Vedi sezione precedente `deploy/package.sh` + `deploy/setup-oracle.sh`: la VM
non dorme mai (nessun compromesso), usa `docker-compose.yml` con il servizio
`tor` separato e `Dockerfile.oc` per l'app, volume `./data` persistente.

## Nota importante

Nessun modello predice il calcio: i pronostici stimano le probabilità dagli
output delle partite passate e dalle quote di mercato. Usali con giudizio;
le scommesse comportano rischi e in Italia sono riservate ai maggiorenni.
L'uso degli scraper è a titolo personale e non ti esonera dal rispetto dei
termini di servizio dei siti coinvolti.