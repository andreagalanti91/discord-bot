@echo off
REM Avvio completo in locale (Windows): login -> sync -> analisi -> dashboard -> alert.
cd /d "%~dp0"

if not exist .venv (
  echo Preparo l'ambiente Python (solo la prima volta)...
  py -3 -m venv .venv || python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
python -m playwright install chromium >nul

findstr /r /c:"^DISCORD_USER_TOKEN=." /c:"^DISCORD_BOT_TOKEN=." .env >nul 2>&1
if errorlevel 1 (
  echo Login a Discord: si apre una finestra del browser, accedi come sempre.
  python -m chento login || goto :error
)

echo Scarico i messaggi del canale...
python -m chento sync || goto :error
echo Analizzo strategia e performance...
python -m chento analyze || goto :error

echo Dashboard: http://localhost:8000/dashboard/
start "Chento dashboard" /min python -m chento serve
timeout /t 2 >nul
start http://localhost:8000/dashboard/

echo Alert in tempo reale attivi (Ctrl+C per uscire).
python -m chento watch
goto :eof

:error
echo.
echo Si e' verificato un errore: copia il messaggio qui sopra (senza token) e mandalo.
pause
