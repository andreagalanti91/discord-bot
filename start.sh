#!/usr/bin/env bash
# Avvio completo in locale (macOS / Linux): login → sync → analisi → dashboard → alert.
set -e
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
if [ ! -d .venv ]; then
  echo "▸ Preparo l'ambiente Python (solo la prima volta)…"
  $PY -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt
python -m playwright install chromium >/dev/null

if ! grep -qs '^DISCORD_USER_TOKEN=.\+' .env && ! grep -qs '^DISCORD_BOT_TOKEN=.\+' .env; then
  echo "▸ Login a Discord: si apre una finestra del browser, accedi come sempre."
  python -m chento login
fi

echo "▸ Scarico i messaggi del canale…"
python -m chento sync
echo "▸ Analizzo strategia e performance…"
python -m chento analyze

echo "▸ Dashboard: http://localhost:8000/dashboard/"
python -m chento serve >/dev/null 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null' EXIT
sleep 1
(command -v open >/dev/null && open http://localhost:8000/dashboard/) || \
  (command -v xdg-open >/dev/null && xdg-open http://localhost:8000/dashboard/) || true

echo "▸ Alert in tempo reale attivi (Ctrl+C per uscire)."
python -m chento watch
