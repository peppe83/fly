<#
    deploy.ps1 — Deploy di "fly" sul VPS Windows di produzione.

    Esegue, in ordine:
      1. allinea il codice al branch remoto (git fetch + reset --hard)
      2. aggiorna le dipendenze SOLO se requirements.txt è cambiato (o -Force)
      3. riavvia il servizio uvicorn (NSSM) e verifica /healthz
    Il worker (Task Scheduler "flynotify-worker") usa run_worker.bat dalla
    cartella: non va riavviato, prenderà il nuovo codice al ciclo successivo.

    Usato sia dal workflow GitHub Actions (self-hosted runner) sia, volendo,
    da un'attività pianificata o a mano. NON tocca il file .env (è gitignorato).

    Esempi:
      powershell -ExecutionPolicy Bypass -File scripts\deploy.ps1
      powershell -ExecutionPolicy Bypass -File scripts\deploy.ps1 -Force
#>
param(
    [string]$AppDir     = "D:\webserver\apache24\flynotify",  # cartella dell'app sul VPS
    [string]$Branch     = "main",
    [string]$Service    = "flynotify",                        # nome servizio NSSM
    [int]   $HealthPort = 8000,
    [switch]$Force                                            # forza pip install anche se requirements invariato
)

$ErrorActionPreference = "Stop"
function Log($m) { Write-Host ("[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m) }

if (-not (Test-Path $AppDir)) { throw "Cartella app non trovata: $AppDir" }
Set-Location $AppDir
Log "Deploy avviato in $AppDir (branch $Branch)"

# 1) Allinea il codice al remoto -----------------------------------------
$before = (git rev-parse HEAD).Trim()
git fetch --all --prune
git checkout $Branch
git reset --hard "origin/$Branch"          # il VPS rispecchia ESATTAMENTE il remoto
$after = (git rev-parse HEAD).Trim()
if ($before -eq $after) { Log "Nessuna novità (HEAD $after)" } else { Log "Codice: $before -> $after" }

# 2) Dipendenze ----------------------------------------------------------
$py = Join-Path $AppDir ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Log "Creo il virtualenv"; & python -m venv .venv }

$reqChanged = $Force -or ($before -eq $after)
if (-not $reqChanged) {
    $diff = git diff --name-only $before $after
    if ($diff -match "requirements\.txt") { $reqChanged = $true }
}
if ($reqChanged) {
    Log "Aggiorno le dipendenze"
    & $py -m pip install --upgrade pip
    & $py -m pip install -r requirements.txt
} else {
    Log "requirements.txt invariato: salto pip install"
}

# 3) Schema DB: l'app applica le migrazioni all'avvio (run_migrations).

# 4) Riavvia il servizio e verifica la salute ----------------------------
Log "Riavvio servizio '$Service' (NSSM)"
& nssm restart $Service
Start-Sleep -Seconds 4

$url = "http://127.0.0.1:$HealthPort/healthz"
try {
    $r = Invoke-WebRequest -UseBasicParsing $url -TimeoutSec 15
    Log ("Health {0}: HTTP {1}" -f $url, $r.StatusCode)
} catch {
    Log "ERRORE: health check fallito su $url - $($_.Exception.Message)"
    throw
}

Log "Deploy completato con successo."
