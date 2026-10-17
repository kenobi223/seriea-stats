# Comandi bot Telegram per NxCreate (SaroBET @SaroBet_bot)

Ogni file in `commands/` va incollato come comando nel console NxCreate
(`https://console.nxcreate.com` → bot SaroBET → tab **Commands** →
**New Command**):

1. **Command**: `/start` (o `/schedina`, `/pronostici`, ...)
2. **Script**: contenuto completo del file corrispondente
3. Salva e ripeti per ogni comando

## Variabile d'ambiente (tab Settings → Environment)

| Nome         | Valore                                                              |
|--------------|---------------------------------------------------------------------|
| `API_BASE`   | URL della facciata Cloudflare Workers, es. `https://seriea-stats.<acct>.workers.dev` |

Il bot legge i dati dalla stessa API del sito (Worker → Upstash Redis),
quindi sito e bot mostrano **gli stessi numeri**.

## Limite piano free

~4 secondi per messaggio: ogni comando fa UNA sola chiamata HTTP a
`/api/state` o `/api/schedina` (tipicamente <1s da Upstash).

## Comandi

| Comando      | Fonte API          | Cosa mostra                                        |
|--------------|--------------------|----------------------------------------------------|
| `/start`     | —                  | menu                                               |
| `/schedina`  | `/api/schedina`    | esiti della giornata + storico vinti/persi         |
| `/pronostici`| `/api/state`       | prossime partite con probabilità e migliori scommesse |
| `/classifica`| `/api/state`       | classifica Serie A                                 |
| `/risultati` | `/api/state`       | risultati ultime giornate                          |
| `/aiuto`     | —                  | elenco comandi                                     |
