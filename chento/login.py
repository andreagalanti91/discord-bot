"""Login con il proprio account Discord tramite browser (da eseguire sul proprio PC).

Apre la pagina ufficiale https://discord.com/login in una finestra di Chromium: l'utente fa
il login (anche con 2FA/QR) e il tool intercetta il token di sessione dalle richieste che il
client web invia alle API. Il token viene salvato SOLO nel file .env locale (permessi 600).

Attenzione: usare il token del proprio account da uno script è contro i Termini di Discord
e può portare al ban dell'account. Il tool lo usa solo in lettura e a ritmo lento.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

from .config import CONFIG, ROOT

ENV = ROOT / ".env"


def _save_env(key: str, value: str) -> None:
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    lines = [ln for ln in lines if not ln.startswith(f"{key}=")]
    lines.append(f"{key}={value}")
    ENV.write_text("\n".join(lines) + "\n")
    os.chmod(ENV, 0o600)


USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
QR_SELECTOR = '[class*="qrCode"]'


def _has_display() -> bool:
    return os.name == "nt" or os.uname().sysname == "Darwin" or bool(
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def capture_token(timeout_s: int = 600, qr_path: Path | None = None) -> str:
    """Senza `qr_path` apre una finestra di login; con `qr_path` gira senza schermo e salva
    l'immagine del QR code (aggiornata quando Discord la rigenera) da scansionare con l'app."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise SystemExit(
            "Serve Playwright: pip install playwright && python -m playwright install chromium"
        ) from e
    headless = qr_path is not None
    if not headless and not _has_display():
        raise SystemExit("Nessuno schermo disponibile: usa `python -m chento login --qr qr.png`.")

    token: dict[str, str] = {}

    def on_request(req):
        auth = req.headers.get("authorization")
        if auth and "discord.com/api" in req.url and not auth.startswith(("Bot ", "Bearer ")):
            token["v"] = auth

    with sync_playwright() as p:
        exe = os.environ.get("CHENTO_CHROMIUM")
        browser = p.chromium.launch(headless=headless, executable_path=exe or None)
        page = browser.new_context(user_agent=USER_AGENT, viewport={"width": 1100, "height": 760}).new_page()
        page.on("request", on_request)
        page.goto("https://discord.com/login")
        if headless:
            print(f"Scansiona il QR in {qr_path} con l'app Discord (Impostazioni → Scansiona codice QR) e conferma.",
                  flush=True)
        else:
            print("Fai il login nella finestra del browser (puoi usare anche il QR code dall'app).")
        deadline = time.time() + timeout_s
        last_qr = b""
        while "v" not in token and time.time() < deadline:
            if headless:
                qr = page.locator(QR_SELECTOR).first
                try:
                    if qr.is_visible():
                        png = qr.screenshot()
                        if png != last_qr:
                            qr_path.write_bytes(png)
                            last_qr = png
                            print(f"QR aggiornato: {qr_path}", flush=True)
                except Exception:  # il QR viene ridisegnato: riprova al giro dopo
                    pass
            page.wait_for_timeout(1500)
        browser.close()
    if qr_path and qr_path.exists():
        qr_path.unlink()
    if "v" not in token:
        raise SystemExit("Login non completato entro il tempo limite.")
    return token["v"]


def login(qr_path: Path | None = None) -> None:
    from .discord_fetch import DiscordClient

    tok = capture_token(qr_path=qr_path)
    CONFIG.user_token, CONFIG.discord_token = tok, ""
    client = DiscordClient(CONFIG)
    me = client.me()
    print(f"Login riuscito come {me.get('global_name') or me.get('username')} ({me['id']}).")
    try:
        last = client.messages(CONFIG.channel_id, limit=1)
        print(f"Accesso al canale {CONFIG.channel_id}: OK" + (f" (ultimo messaggio {last[0]['timestamp']})" if last else ""))
    except SystemExit as e:
        print(f"Attenzione, canale non leggibile: {e}")
    _save_env("DISCORD_USER_TOKEN", tok)
    print(f"Token salvato in {ENV} (solo su questo computer, non va mai condiviso o committato).")
    print("Ora: python -m chento sync && python -m chento analyze && python -m chento serve")


def logout() -> None:
    if ENV.exists():
        ENV.write_text("".join(ln + "\n" for ln in ENV.read_text().splitlines()
                               if not re.match(r"DISCORD_USER_TOKEN=", ln)))
    print("Token rimosso dal file .env. Per invalidarlo davvero: Discord → Impostazioni → Dispositivi → disconnetti la sessione.")
