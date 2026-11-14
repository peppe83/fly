@echo off
REM Worker flynotify (da lanciare con Windows Task Scheduler ogni ~30 min)
REM Usa la cartella dello script stesso: resta valido anche se la cartella viene rinominata.
cd /d "%~dp0"
if not exist logs mkdir logs
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m app.worker >> logs\worker.log 2>&1
) else (
    python -m app.worker >> logs\worker.log 2>&1
)
