@echo off
REM Avvio del server web flynotify (sviluppo)
REM Usa la cartella dello script stesso: resta valido anche se la cartella viene rinominata.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
) else (
    uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
)
