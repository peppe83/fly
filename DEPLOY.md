# Deploy di flynotify — VPS Windows + Apache 2.4

Architettura di produzione:

```
Internet ──HTTPS(443)──► Apache 2.4 (reverse proxy) ──HTTP(127.0.0.1:8000)──► uvicorn (servizio Windows)
                                                                                      │
                                                                                      ▼
                                                                                 MySQL 8
Windows Task Scheduler ──► run_worker.bat (alert + email, ogni ~30 min)
```

- **uvicorn** gira come **servizio Windows** (NSSM), in ascolto solo su `127.0.0.1:8000` (non esposto).
- **Apache 2.4** riceve il traffico pubblico su 80/443, termina l'HTTPS e inoltra all'app.
- **MySQL** è il database; **Task Scheduler** esegue il worker.

> Percorso usato in questa guida: `D:\webserver\apache24\flynotify`. Adatta se diverso.

---

## 1. Prerequisiti sul VPS

- Python 3.12/3.13 (consigliato; evita 3.15 finché tutti i wheel non sono pubblicati). Verifica: `python --version`.
- Apache 2.4 (già presente).
- MySQL 8 installato e avviato.
- Un dominio/sottodominio che punta all'IP del VPS (es. `flynotify.tuodominio.it`).
- Porte **80** e **443** aperte nel Windows Firewall (per Apache). La **8000 NON** va aperta all'esterno.

---

## 2. Preparare l'app

Da un prompt (PowerShell o cmd) nella cartella del progetto:

```bat
cd /d D:\webserver\apache24\flynotify
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Crea il file `.env` (copia da `.env.example`) e compila i valori di **produzione**:

```ini
APP_ENV=production
APP_BASE_URL=https://flynotify.tuodominio.it
JWT_SECRET=<stringa lunga e casuale, almeno 40 caratteri>

# Database MySQL (vedi passo 3)
DATABASE_URL=mysql+pymysql://flynotify:PASSWORD@127.0.0.1:3306/flynotify?charset=utf8mb4

# Chiavi provider ed email
AMADEUS_CLIENT_ID=...
AMADEUS_CLIENT_SECRET=...
AMADEUS_BASE_URL=https://api.amadeus.com      # produzione
TRAVELPAYOUTS_TOKEN=...
TRAVELPAYOUTS_MARKER=...
GMAIL_USER=flynotify.alerts@gmail.com
GMAIL_APP_PASSWORD=...
```

> Per generare un `JWT_SECRET`: `python -c "import secrets; print(secrets.token_urlsafe(48))"`

---

## 3. Database MySQL

Nel client MySQL (`mysql -u root -p`):

```sql
CREATE DATABASE flynotify CHARACTER SET utf8mb4;
CREATE USER 'flynotify'@'localhost' IDENTIFIED BY 'PASSWORD_FORTE';
GRANT ALL PRIVILEGES ON flynotify.* TO 'flynotify'@'localhost';
FLUSH PRIVILEGES;
```

Le tabelle vengono create automaticamente al primo avvio dell'app. Per crearle subito
e generare il primo **superadmin**:

```bat
.venv\Scripts\activate
python -m app.seed admin@tuodominio.it LaTuaPassword "Nome Cognome"
```

---

## 4. uvicorn come servizio Windows (NSSM)

Scarica **NSSM** (https://nssm.cc) e metti `nssm.exe` in un percorso comodo, poi:

```bat
nssm install flynotify "D:\webserver\apache24\flynotify\.venv\Scripts\python.exe"
nssm set flynotify AppDirectory "D:\webserver\apache24\flynotify"
nssm set flynotify AppParameters "-m uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips 127.0.0.1"
nssm set flynotify AppStdout "D:\webserver\apache24\flynotify\logs\uvicorn.log"
nssm set flynotify AppStderr "D:\webserver\apache24\flynotify\logs\uvicorn.log"
nssm set flynotify Start SERVICE_AUTO_START
nssm start flynotify
```

Verifica in locale sul VPS: `curl http://127.0.0.1:8000/healthz` → `{"status":"ok",...}`.

Comandi utili: `nssm restart flynotify`, `nssm stop flynotify`, `nssm status flynotify`.

---

## 5. Apache 2.4 come reverse proxy + HTTPS

### 5.1 Abilita i moduli
In `httpd.conf` togli il `#` davanti a queste righe:

```apache
LoadModule proxy_module modules/mod_proxy.so
LoadModule proxy_http_module modules/mod_proxy_http.so
LoadModule headers_module modules/mod_headers.so
LoadModule ssl_module modules/mod_ssl.so
LoadModule rewrite_module modules/mod_rewrite.so
```

### 5.2 VirtualHost
Crea un file (es. `conf/extra/flynotify.conf`) e includilo da `httpd.conf`
(`Include conf/extra/flynotify.conf`):

```apache
<VirtualHost *:80>
    ServerName flynotify.tuodominio.it
    # Forza HTTPS
    RewriteEngine On
    RewriteRule ^/?(.*) https://flynotify.tuodominio.it/$1 [R=301,L]
</VirtualHost>

<VirtualHost *:443>
    ServerName flynotify.tuodominio.it

    SSLEngine on
    SSLCertificateFile    "D:/webserver/certs/flynotify.crt"
    SSLCertificateKeyFile "D:/webserver/certs/flynotify.key"
    # SSLCertificateChainFile "D:/webserver/certs/chain.crt"   # se fornito

    ProxyPreserveHost On
    RequestHeader set X-Forwarded-Proto "https"
    ProxyPass        "/" "http://127.0.0.1:8000/"
    ProxyPassReverse "/" "http://127.0.0.1:8000/"

    ErrorLog  "logs/flynotify-error.log"
    CustomLog "logs/flynotify-access.log" common
</VirtualHost>
```

Controlla la sintassi e riavvia Apache:

```bat
httpd -t
httpd -k restart
```

> L'app serve da sola i file statici su `/static`: nessuna configurazione extra necessaria.
> (Opzionale, per performance: `Alias /static "D:/webserver/apache24/flynotify/static"` servito direttamente da Apache.)

---

## 6. Certificato HTTPS

- **Let's Encrypt (gratis)**: usa **win-acme** (https://www.win-acme.com). In modalità manuale
  genera `.crt` e `.key` e indicali nel VirtualHost, oppure lascia che configuri Apache.
- In alternativa, un **certificato fornito da Aruba**: scarica `.crt` e `.key` e mettili nei percorsi indicati sopra.

Dopo l'installazione, imposta un rinnovo automatico (win-acme crea già un'attività pianificata).

---

## 7. Worker (alert + email) con Task Scheduler

È il **worker** che invia le email di avviso (l'app web no). Gira periodicamente e, a
ogni esecuzione: prende gli utenti il cui intervallo (`poll_interval_hours`) è scaduto,
valuta i loro alert attivi, aggiorna lo storico prezzi e — se un alert scatta — invia
**una sola email riepilogativa** per utente, poi aggiorna `last_run_at`. Non manda email
a ogni giro: solo quando c'è qualcosa di nuovo (con deduplica e tetto `EMAIL_DAILY_CAP`).
La strategia "buon affare" notifica dal **secondo** giro in poi (il primo crea la baseline).
Richiede nel `.env`: `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `ENABLE_ALERTS=true`.

Il worker è già pronto in `run_worker.bat` (indipendente dal percorso: usa la propria
cartella e il `python.exe` del `.venv`). Registra l'attività (prompt come **amministratore**):

```bat
schtasks /Create /TN "fly-worker" /TR "C:\webserver\python\fly\run_worker.bat" /SC MINUTE /MO 30 /RU SYSTEM /RL HIGHEST /F
```

Nelle proprietà dell'attività (Utilità di pianificazione) consigliato spuntare:
- **Non avviare una nuova istanza** se è già in esecuzione;
- **Esegui l'attività il prima possibile dopo un avvio pianificato non riuscito**.

Assicurati che il VPS **non vada in sospensione** (di norma un server è sempre acceso).

Prova manuale e verifica:
```bat
schtasks /Run /TN "fly-worker"
type C:\webserver\python\fly\logs\worker.log
```
Stato dei cicli nella tabella `run_log` del database; email inviate in `email_log`.
Per forzare un giro completo subito, azzera `last_run_at` dell'utente sul DB di produzione
(il worker salta gli utenti elaborati da meno di `poll_interval_hours`).

---

## 8. Sicurezza e verifica finale

- `.env` con `APP_ENV=production` → i cookie di sessione sono **Secure** (solo HTTPS).
- `JWT_SECRET` lungo e casuale; non versionare `.env` (già in `.gitignore`).
- La porta **8000** resta su `127.0.0.1` (non apribile da fuori): espone solo Apache (80/443).
- Limita l'accesso al file `.env` all'utente del servizio.
- Verifica dall'esterno: apri `https://flynotify.tuodominio.it` → deve comparire la home;
  registra un utente e prova la ricerca.

---

## 9. Aggiornamenti e manutenzione

Per aggiornare l'app dopo modifiche:

```bat
cd /d D:\webserver\apache24\flynotify
.venv\Scripts\activate
pip install -r requirements.txt   # se cambiano le dipendenze
nssm restart flynotify
```

Log utili:
- app/web: `logs\uvicorn.log`
- worker: `logs\worker.log`
- Apache: `logs\flynotify-error.log` / `flynotify-access.log`
- stato dei cicli worker: tabella `run_log` nel database.

---

### Riepilogo porte/servizi
| Componente | Porta | Esposto a |
|---|---|---|
| Apache (HTTP→HTTPS) | 80 | pubblico |
| Apache (HTTPS) | 443 | pubblico |
| uvicorn (flynotify) | 8000 | solo 127.0.0.1 |
| MySQL | 3306 | solo locale |

---


## 10. Auto-deploy con self-hosted runner (stesso schema di "leggimi")

A ogni `push` su `main`: i **test** girano sul cloud GitHub (`ubuntu-latest`), poi un
**runner self-hosted** sulla VPS esegue `strumenti\aggiorna.ps1`, che **copia** il codice
in produzione (robocopy, niente git lato server) e riavvia il servizio NSSM, preservando
`.env`, `.venv\`, `logs\`, `backup\`.

Convenzioni (gemelle di leggimi):

| | leggimi | **fly** |
|---|---|---|
| Cartella produzione | `C:\webserver\python\leggimi` | `C:\webserver\python\fly` |
| Servizio NSSM | `my-leggimi` | `my-fly` |
| Porta uvicorn | 5010 | **5020** |
| Label runner | `leggimi` | `fly` |
| Health check | `/api/salute` | `/healthz` |

### 10.1 Primo setup della produzione (una tantum)
```powershell
# 1. Cartella e codice iniziale (il runner poi aggiornerà da solo)
mkdir C:\webserver\python\fly
# copia qui una prima volta il contenuto del repo, oppure lascia che lo faccia il primo deploy
#   (in quel caso crea almeno .env e .venv come sotto)

# 2. .env di produzione (NON versionato) — parti da .env.example
#    Imposta almeno:
#      APP_ENV=production
#      PORT=5020
#      APP_BASE_URL=https://fly.tuodominio.it
#      JWT_SECRET=<stringa lunga e casuale>
#      DATABASE_URL=mysql+pymysql://fly:PASSWORD@127.0.0.1:3306/fly?charset=utf8mb4
#      (chiavi provider + Gmail)

# 3. Virtualenv + dipendenze (Python 3.15 installato "per tutti gli utenti")
cd C:\webserver\python\fly
py -3.15 -m venv .venv
.venv\Scripts\python -m pip install -U pip -r requirements.txt

# 4. Servizio NSSM "my-fly" sulla porta 5020 (solo su 127.0.0.1)
nssm install my-fly "C:\webserver\python\fly\.venv\Scripts\python.exe"
nssm set my-fly AppDirectory "C:\webserver\python\fly"
nssm set my-fly AppParameters "-m uvicorn app.main:app --host 127.0.0.1 --port 5020 --proxy-headers --forwarded-allow-ips 127.0.0.1"
nssm set my-fly AppStdout "C:\webserver\python\fly\logs\uvicorn.log"
nssm set my-fly AppStderr "C:\webserver\python\fly\logs\uvicorn.log"
nssm set my-fly Start SERVICE_AUTO_START
nssm start my-fly
curl http://127.0.0.1:5020/healthz
```
Apache: aggiungi un VirtualHost per `fly.tuodominio.it` che fa da reverse proxy verso
`http://127.0.0.1:5020/` (vedi sezione 5, cambiando solo ServerName e porta).
Worker: registra l'attività pianificata come in sezione 7, usando `run_worker.bat`
della cartella `C:\webserver\python\fly`.

### 10.2 Aggiungi il runner per il repo "fly" (una tantum)
Il runner esistente `C:\webserver\actions-runner` è legato a **leggimi**; per `fly` se ne
aggiunge un **secondo**, in una cartella separata:
1. Su GitHub: **https://github.com/peppe83/fly → Settings → Actions → Runners → New self-hosted runner** (Windows). Copia il **token**.
2. Sulla VPS:
   ```powershell
   mkdir C:\webserver\actions-runner-fly ; cd C:\webserver\actions-runner-fly
   # scarica/estrai qui l'actions-runner (stessa versione dell'altro runner va bene)
   .\config.cmd --url https://github.com/peppe83/fly --token <TOKEN> --labels fly --unattended --name fly-vps
   .\svc.cmd install
   .\svc.cmd start
   ```
3. Il servizio del runner deve poter gestire `my-fly`: nelle sue proprietà (services.msc)
   impostalo **Log on as** un amministratore locale (come il runner di leggimi).

### 10.3 Come funziona a regime
- `push` su `main` → test su GitHub → `deploy` sul runner `fly` → `strumenti\aggiorna.ps1`.
- Variabili facoltative del repo (Settings → Actions → Variables): `FLY_CARTELLA`, `FLY_SERVIZIO`.
- Avvio manuale: **Actions → Test e pubblicazione → Run workflow**.

### 10.4 Deploy manuale (senza push)
Sulla VPS, da una copia aggiornata del codice:
```powershell
powershell -ExecutionPolicy Bypass -File strumenti\aggiorna.ps1 -Sorgente C:\percorso\copia-fly
```
