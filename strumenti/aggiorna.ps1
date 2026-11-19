<#
Aggiorna "fly" in produzione sulla VPS Windows (stesso schema di leggimi).

Lo usa la GitHub Action a ogni push, ma si può lanciare anche a mano da una copia del codice:
    powershell -ExecutionPolicy Bypass -File strumenti\aggiorna.ps1 -Sorgente C:\sorgenti\fly

Non tocca mai .env, logs\, backup\ e .venv\ nella cartella di produzione.
#>
param(
    [Parameter(Mandatory = $true)] [string] $Sorgente,
    [string] $Destinazione = "C:\webserver\python\fly",
    [string] $Servizio = "my-fly",
    [string] $Versione = (Get-Date -Format "yyyyMMdd-HHmm"),
    # Versione di Python del progetto (la stessa dei test nella GitHub Action)
    [string] $VersionePython = "3.15"
)

$ErrorActionPreference = "Stop"

function Passo([string] $testo) { Write-Host "`n=== $testo ===" }

function Leggi-Env([string] $file) {
    $valori = @{}
    foreach ($riga in Get-Content $file -Encoding UTF8) {
        $riga = $riga.Trim()
        if ($riga -eq "" -or $riga.StartsWith("#") -or -not $riga.Contains("=")) { continue }
        $i = $riga.IndexOf("=")
        $valori[$riga.Substring(0, $i).Trim()] = $riga.Substring($i + 1).Trim().Trim('"').Trim("'")
    }
    return $valori
}

function Esegui([string] $programma, [string[]] $argomenti) {
    & $programma @argomenti
    if ($LASTEXITCODE -ne 0) { throw "Comando fallito ($LASTEXITCODE): $programma $($argomenti -join ' ')" }
}

$fileEnv = Join-Path $Destinazione ".env"
if (-not (Test-Path $fileEnv)) {
    throw "Manca ${fileEnv}: crealo a mano partendo da .env.example prima del primo deploy."
}
$config = Leggi-Env $fileEnv
$porta = if ($config["PORT"]) { $config["PORT"] } else { "5020" }

# L'account del runner deve poter scrivere nella cartella: meglio scoprirlo prima di fermare il servizio.
$account = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$prova = Join-Path $Destinazione ".prova-scrittura"
try {
    Set-Content -Path $prova -Value "ok" -ErrorAction Stop
    Remove-Item $prova -Force -ErrorAction Stop
} catch {
    throw "L'account $account non puo scrivere in ${Destinazione}. Dai i permessi con: icacls `"$Destinazione`" /grant `"${account}:(OI)(CI)M`" /T"
}

function Trova([string] $nome, [string[]] $percorsi) {
    $comando = (Get-Command $nome -ErrorAction SilentlyContinue).Source
    if ($comando) { return $comando }
    foreach ($schema in $percorsi) {
        $trovato = Get-ChildItem $schema -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
        if ($trovato) { return $trovato.FullName }
    }
    return $null
}

function Versione-Python([string] $eseguibile) {
    try { return (& $eseguibile -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null | Select-Object -First 1) }
    catch { return $null }
}

# Il runner gira come servizio: non vede i Python installati "solo per l'utente" ne il suo PATH personale.
function Trova-Python {
    $senzaPunto = $VersionePython -replace "\.", ""
    $candidati = @(
        "$env:ProgramFiles\Python$senzaPunto\python.exe",
        "${env:ProgramFiles(x86)}\Python$senzaPunto\python.exe",
        "C:\Python$senzaPunto\python.exe"
    )
    $py = (Get-Command py -ErrorAction SilentlyContinue).Source
    if ($py) {
        try {
            $daPy = & $py "-$VersionePython" -c "import sys; print(sys.executable)" 2>$null | Select-Object -First 1
            if ($LASTEXITCODE -eq 0 -and $daPy) { $candidati = @($daPy) + $candidati }
        } catch { }  # py scrive su stderr se quella versione non c'e
        $global:LASTEXITCODE = 0
    }
    $candidati += (Get-Command python -All -ErrorAction SilentlyContinue | ForEach-Object Source)
    $visti = @()
    foreach ($c in $candidati) {
        if (-not $c -or -not (Test-Path $c)) { continue }
        $v = Versione-Python $c
        $visti += "$c ($v)"
        if ($v -eq $VersionePython) { return $c }
    }
    throw ("Python $VersionePython non trovato. Installalo 'per tutti gli utenti' (in $env:ProgramFiles\Python$senzaPunto). " +
           "Trovati: " + ($(if ($visti) { $visti -join ", " } else { "nessuno" })))
}

# 1. Backup del database prima di toccare qualsiasi cosa
Passo "Backup del database"
$mysqldump = Trova "mysqldump" @("$env:ProgramFiles\MySQL\*\bin\mysqldump.exe", "C:\webserver\mysql*\bin\mysqldump.exe",
                                 "C:\webserver\*\mysql*\bin\mysqldump.exe")
if ($mysqldump -and $config["DATABASE_URL"] -match "^mysql\+pymysql://([^:]+):([^@]*)@([^/:]+)(?::(\d+))?/([^?]+)") {
    $cartellaBackup = Join-Path $Destinazione "backup"
    New-Item -ItemType Directory -Force $cartellaBackup | Out-Null
    $fileBackup = Join-Path $cartellaBackup "prima-di-$Versione.sql"
    $env:MYSQL_PWD = [uri]::UnescapeDataString($Matches[2])
    try {
        $argomenti = @("--single-transaction", "--routines", "--no-tablespaces", "-u", $Matches[1], "-h", $Matches[3], "--result-file=$fileBackup")
        if ($Matches[4]) { $argomenti += @("-P", $Matches[4]) }
        Esegui $mysqldump ($argomenti + $Matches[5])
    } finally {
        Remove-Item Env:\MYSQL_PWD -ErrorAction SilentlyContinue
    }
    # tiene solo gli ultimi 10 backup fatti dagli aggiornamenti
    Get-ChildItem $cartellaBackup -Filter "prima-di-*.sql" | Sort-Object LastWriteTime -Descending |
        Select-Object -Skip 10 | Remove-Item -Force
    Write-Host "Backup salvato in $fileBackup"
} else {
    Write-Warning "mysqldump non disponibile o DATABASE_URL non MySQL: backup saltato."
}

# 2. Arresto del servizio
Passo "Arresto del servizio $Servizio"
$esisteServizio = [bool](Get-Service -Name $Servizio -ErrorAction SilentlyContinue)
if ($esisteServizio) {
    $nssm = Trova "nssm" @("C:\webserver\nssm*\win64\nssm.exe", "C:\webserver\nssm*\nssm.exe", "C:\nssm*\win64\nssm.exe",
                           "$env:ProgramFiles\nssm*\win64\nssm.exe")
    if (-not $nssm) { throw "NSSM non trovato: mettilo nel PATH di sistema." }
    $comandoPermesso = "`$sd = (sc.exe sdshow $Servizio | Where-Object { `$_ }).Trim(); sc.exe sdset $Servizio (`$sd -replace '^(D:(?:\([^)]*\))*)', '`$1(A;;RPWPLCLOCRRC;;;NS)')"
    & $nssm stop $Servizio | Out-Host
    $limite = (Get-Date).AddSeconds(60)
    while ((Get-Service -Name $Servizio).Status -ne "Stopped" -and (Get-Date) -lt $limite) { Start-Sleep -Seconds 1 }
    # Se l'account del runner non puo gestire il servizio, meglio fermarsi prima di copiare il codice:
    # altrimenti resterebbe in esecuzione la versione vecchia e il controllo di salute passerebbe lo stesso.
    if ((Get-Service -Name $Servizio).Status -ne "Stopped") {
        throw ("Il servizio $Servizio non si e fermato. Se sopra c'e 'Access is denied', l'account $account non puo gestirlo: " +
               "fai girare il runner come LocalSystem oppure, da amministratore, lancia: $comandoPermesso")
    }
} else {
    Write-Warning "Il servizio $Servizio non esiste ancora: registralo con NSSM (vedi DEPLOY.md)."
}

try {
    # 3. Copia del codice: /MIR toglie i file non piu presenti, le esclusioni restano intatte
    Passo "Copia del codice in $Destinazione"
    $escluseCartelle = @(".git", ".github", ".venv", ".claude", "logs", "backup", "test", "tests", "docs", "__pycache__", ".pytest_cache")
    $esclusiFile = @(".env", "*.pyc", "*.db")
    $argomenti = @($Sorgente, $Destinazione, "/MIR", "/NFL", "/NDL", "/NP", "/R:2", "/W:2", "/XD") + $escluseCartelle +
                 @("/XF") + $esclusiFile
    & robocopy @argomenti | Out-Host
    if ($LASTEXITCODE -ge 8) { throw "robocopy non e riuscito a copiare i file (codice $LASTEXITCODE)." }
    $global:LASTEXITCODE = 0
    # robocopy a volte segnala come riuscita una copia mai avvenuta (es. accesso negato alla cartella di arrivo)
    foreach ($necessario in @("requirements.txt", "app\main.py")) {
        if (-not (Test-Path (Join-Path $Destinazione $necessario))) {
            throw "Dopo la copia manca $necessario in ${Destinazione}: controlla i permessi dell'account $account."
        }
    }

    # 4. Dipendenze (le migrazioni le applica l'app all'avvio: run_migrations)
    Passo "Dipendenze"
    $cartellaVenv = Join-Path $Destinazione ".venv"
    $python = Join-Path $cartellaVenv "Scripts\python.exe"
    # Un ambiente creato con un'altra versione di Python (es. dal primo deploy) va rifatto da capo.
    if ((Test-Path $python) -and (Versione-Python $python) -ne $VersionePython) {
        Write-Host "L'ambiente virtuale usa Python $(Versione-Python $python), serve $VersionePython`: lo ricreo"
        Remove-Item -Recurse -Force $cartellaVenv
    }
    if (-not (Test-Path $python)) {
        $pythonSistema = Trova-Python
        Write-Host "Creo l'ambiente virtuale con $pythonSistema"
        Esegui $pythonSistema @("-m", "venv", $cartellaVenv)
    }
    Esegui $python @("-m", "pip", "install", "--quiet", "--upgrade", "pip", "certifi")
    Esegui $python @("-m", "pip", "install", "--quiet", "-r", (Join-Path $Destinazione "requirements.txt"))
} finally {
    # 5. Riavvio, anche se un passo sopra e fallito: meglio la versione precedente accesa che il servizio spento
    if ($esisteServizio) {
        Passo "Avvio del servizio $Servizio"
        & $nssm start $Servizio | Out-Host
    }
}

if ($esisteServizio) {
    $limite = (Get-Date).AddSeconds(30)
    while ((Get-Service -Name $Servizio).Status -ne "Running" -and (Get-Date) -lt $limite) { Start-Sleep -Seconds 1 }
    if ((Get-Service -Name $Servizio).Status -ne "Running") {
        throw "Il servizio $Servizio non e ripartito (stato: $((Get-Service -Name $Servizio).Status)). Avvialo con: nssm start $Servizio"
    }
}

if ($esisteServizio) {
    Passo "Controllo di /healthz"
    $url = "http://127.0.0.1:$porta/healthz"
    $limite = (Get-Date).AddSeconds(60)
    $ok = $false
    while ((Get-Date) -lt $limite) {
        try {
            $risposta = Invoke-RestMethod -Uri $url -TimeoutSec 5
            if ($risposta.status -eq "ok") { $ok = $true; break }
            Write-Host "Stato: $($risposta | ConvertTo-Json -Compress)"
        } catch {
            Write-Host "In attesa del servizio... ($($_.Exception.Message))"
        }
        Start-Sleep -Seconds 3
    }
    if (-not $ok) { throw "Il servizio non risponde correttamente su ${url}: controlla logs\uvicorn.log." }
}

Write-Host "`nfly aggiornato alla versione $Versione."
