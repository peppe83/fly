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

Il worker è già pronto in `run_worker.bat`. Registralo (da prompt come amministratore):

```bat
schtasks /Create /TN "flynotify-worker" /TR "D:\webserver\apache24\flynotify\run_worker.bat" /SC MINUTE /MO 30 /RU SYSTEM /RL LIMITED /F
```

Nelle proprietà dell'attività (Utilità di pianificazione) consigliato spuntare:
- **Non avviare una nuova istanza** se è già in esecuzione;
- **Esegui l'attività il prima possibile dopo un avvio pianificato non riuscito**.

Assicurati che il VPS **non vada in sospensione** (di norma un server è sempre acceso).
Prova manuale: `.venv\Scripts\python.exe -m app.worker` e controlla `logs\worker.log`.

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

## 10. Auto-deploy con self-hosted runner (push → deploy)

Obiettivo: a ogni `git push` su `main`, il VPS aggiorna il codice e riavvia il
servizio **da solo**, tramite un **GitHub Actions self-hosted runner** che gira
sul VPS ed esegue `scripts\deploy.ps1`.

### 10.1 Prerequisiti sul VPS
- Il progetto è un **clone git** del repo (`git clone https://github.com/peppe83/fly.git`)
  nella cartella dell'app (es. `D:\webserver\apache24\flynotify`), con `.venv` e `.env` già configurati.
- `git` e `nssm` raggiungibili nel PATH dell'utente che eseguirà il runner.
- Il servizio NSSM `flynotify` già installato (sezione 4) e il worker (sezione 7).

### 10.2 Installa il runner (una tantum)
1. Su GitHub: **Settings → Actions → Runners → New self-hosted runner**, OS **Windows**.
2. Segui i comandi mostrati (scarica ed estrai l'`actions-runner` in es. `D:\actions-runner`), poi configura:
   ```powershell
   cd D:\actions-runner
   .\config.cmd --url https://github.com/peppe83/fly --token <TOKEN_MOSTRATO_DA_GITHUB> --labels fly-prod --unattended
   ```
   Le label risultanti devono includere `self-hosted, Windows, fly-prod` (combaciano con `deploy.yml`).
3. Installa il runner **come servizio** (parte all'avvio del VPS):
   ```powershell
   .\svc.cmd install
   .\svc.cmd start
   ```
   > Esegui il runner con un utente che abbia i permessi per `nssm restart flynotify`
   > (nelle proprietà del servizio del runner, imposta "Log on as" un amministratore locale).

### 10.3 Come funziona
- Il workflow `.github/workflows/deploy.yml` scatta su **push a `main`** (salta i soli `.md`), oppure a mano da **Actions → Deploy produzione → Run workflow**.
- Esegue `scripts\deploy.ps1`, che:
  1. `git fetch` + `git reset --hard origin/main` (il VPS rispecchia esattamente il remoto; `.env` è gitignorato e resta intatto);
  2. `pip install -r requirements.txt` **solo** se `requirements.txt` è cambiato;
  3. `nssm restart flynotify` e verifica `http://127.0.0.1:8000/healthz`.
- Il worker prende il nuovo codice al ciclo successivo (nessun riavvio necessario).

### 10.4 Alternativa senza runner: attività pianificata
Se preferisci non installare il runner, programma lo stesso script in pull ogni 10 minuti:
```bat
schtasks /Create /TN "fly-deploy" /SC MINUTE /MO 10 /RU SYSTEM /RL HIGHEST /F ^
  /TR "powershell -ExecutionPolicy Bypass -File D:\webserver\apache24\flynotify\scripts\deploy.ps1"
```
Lo script è idempotente: se non ci sono novità sul remoto, non riavvia nulla di inutile
(fa comunque il restart solo quando `HEAD` cambia o `requirements.txt` cambia).

### 10.5 Deploy manuale
In qualsiasi momento, sul VPS:
```powershell
powershell -ExecutionPolicy Bypass -File D:\webserver\apache24\flynotify\scripts\deploy.ps1 -Force
```
