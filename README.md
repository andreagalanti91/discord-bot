# Chento Tracker

Analizza i messaggi di **Chento** nel canale Discord `1547586761515860069`, ricostruisce la sua
strategia di trading, misura la performance reale di ogni segnale sul prezzo, la replica 1:1,
propone una strategia derivata (**Chento+**), confronta le due e invia un alert per ogni suo nuovo
messaggio. Il tutto in una dashboard in stile Apple (light/dark, desktop/mobile).

```
Discord ──sync/watch──▶ SQLite ──parser (+Claude per testo e grafici)──▶ segnali
                                                                          │
              Yahoo Finance (crypto, forex, oro, indici, azioni) ──▶ backtest candle-by-candle
                                                                          │
                     Replica Chento · Chento+ · profilo strategia · pattern ricorrenti
                                                                          │
                             dashboard/ (HTML statico)  ·  alert su console + webhook Discord
```

## Avvio in un comando (sul tuo PC)

1. Scarica il progetto: su GitHub → branch `claude/ecstatic-goodall-kdt6zo` → **Code → Download ZIP**, ed estrailo.
2. Avvia:
   - **Windows**: doppio clic su `start.bat`
   - **macOS / Linux**: apri il Terminale nella cartella e lancia `./start.sh`

La prima volta si apre la pagina di login di Discord: accedi come sempre. Poi lo script scarica i
messaggi, fa l'analisi, apre la dashboard e resta in ascolto per gli alert. Serve Python 3.10+
(python.org). Se dice che non trova messaggi di Chento, imposta `CHENTO_AUTHOR_ID` nel file `.env`
con l'id mostrato e rilancia.

## Avvio rapido (comandi singoli)

```bash
pip install -r requirements.txt
cp .env.example .env            # inserisci DISCORD_BOT_TOKEN (e opzionalmente ANTHROPIC_API_KEY)

python -m chento sync           # scarica tutto lo storico del canale (+ immagini)
python -m chento analyze        # segnali → backtest → profilo → dashboard
python -m chento serve          # http://localhost:8000/dashboard/
python -m chento watch          # alert in tempo reale per ogni nuovo messaggio di Chento
```

Per provare senza Discord: `python -m chento demo && python -m chento analyze --no-ai`.
La demo usa messaggi **sintetici** (marcati DEMO nella dashboard) su prezzi storici reali.

### Opzione A — login con il tuo account (sul tuo PC)
> ⚠️ Usare il proprio account da uno script è contro i Termini di Discord e può portare al ban.
> Il tool legge soltanto, a ritmo lento, e il token resta nel file `.env` del tuo computer.

```bash
pip install -r requirements.txt && python -m playwright install chromium
python -m chento login     # si apre discord.com/login: accedi (anche 2FA/QR)
python -m chento sync      # scarica i messaggi del canale 1547586761515860069
python -m chento analyze && python -m chento serve
python -m chento watch     # alert in tempo reale
python -m chento logout    # rimuove il token (poi disconnetti la sessione da Discord → Dispositivi)
```
Imposta `CHENTO_AUTHOR_ID` con l'ID di Chento per filtrare solo i suoi messaggi.

### Opzione A2 — export dal tuo account (nessun bot, credenziali solo sul tuo PC)
1. Scarica [DiscordChatExporter](https://github.com/Tyrrrz/DiscordChatExporter) ed eseguilo **sul tuo computer**.
2. Esporta il canale `1547586761515860069` in formato **JSON**, con l'opzione per scaricare i media
   (GUI: "Download assets"; CLI: `--media`).
3. Metti il `.json` e la cartella dei media in `data/export/` e lancia:
   ```bash
   python -m chento import data/export/<file>.json   # mostra gli autori con il loro ID
   CHENTO_AUTHOR_ID=<id di Chento> python -m chento analyze
   ```
Ripeti l'export quando vuoi aggiornare i dati: l'import salta i messaggi già presenti.

### Opzione B — bot Discord (necessaria per gli alert in tempo reale)
1. Developer Portal → New Application → Bot → copia il token in `DISCORD_BOT_TOKEN`.
2. Nella stessa pagina attiva **Message Content Intent**.
3. Invita il bot nel server con i permessi *View Channel* + *Read Message History*
   (serve un admin del server). I token utente/self-bot non sono supportati (violano i ToS).
4. Imposta `CHENTO_AUTHOR_ID` con l'ID utente di Chento (tasto destro → Copia ID utente).

## Cosa fa

| Richiesta | Dove |
|---|---|
| Analisi messaggi del canale | `chento/discord_fetch.py`, `chento/parser.py`, `chento/ai.py` |
| Rilevazione della strategia | `chento/profiler.py` → *fingerprint* (stile, strumenti, timeframe, orizzonte, rischio) |
| Comportamento e pattern ricorrenti | `profiler.insights`: orari, sessioni migliori/peggiori, strumenti a expectancy negativa, re-entry, revenge trading, uso del BE |
| Messaggi con immagini e testo + performance | tab **Messaggi**: testo, screenshot, livelli estratti, esito replica e Chento+ |
| Replica diretta | `strategies.REPLICA`: suoi ingressi, SL, TP equidistribuiti, applica i suoi update (BE, parziali, chiusure) |
| Strategia derivata | `strategies.DERIVED` (**Chento+**): filtri appresi walk-forward + 50% a TP1 e SL a BE |
| Confronto | tab **Confronto**: equity, metriche, distribuzione R, trade dove divergono |
| Alert per ogni messaggio | `python -m chento watch` → console, webhook Discord, tab **Alert** |
| Dashboard | `dashboard/` |

### Come viene misurata la performance
- Ogni segnale viene simulato sulle candele (15m se recente, altrimenti 1h/1d).
- Entry con livello → ordine limit (o stop-entry se il livello è oltre il prezzo); senza livello → a mercato.
- SL e TP toccati nella stessa candela → si assume **prima lo SL** (stima conservativa).
- SL non indicato → stimato con ATR e marcato "SL stimato".
- Risultati in **R** (multipli del rischio) e in % con rischio fisso per trade (`CHENTO_RISK_PCT`).

### Chento+ (strategia derivata)
Usa solo informazioni disponibili *prima* di ogni segnale (nessun lookahead):
- salta R:R < 1.5, segnali ambigui, ingressi già "scappati" (> 50% verso TP1);
- salta simboli e sessioni con expectancy storica negativa nella replica;
- gestione: 50% a TP1 + stop a breakeven, resto sull'ultimo target; TP a 2R se mancano target.

Le regole sono in `chento/strategies.py` e vanno ritarate sui dati reali di Chento: sul dataset demo
(segnali casuali) Chento+ non batte la replica, ed è il risultato atteso.

### Analisi AI (opzionale)
Con `ANTHROPIC_API_KEY` impostata ogni messaggio viene passato a Claude (testo + screenshot del grafico)
per completare i livelli mancanti, riconoscere il setup e scrivere una breve analisi inclusa negli alert.
Senza chiave funziona tutto con il parser a regole (`--no-ai`).

## Test
```bash
python -m pytest -q
```
