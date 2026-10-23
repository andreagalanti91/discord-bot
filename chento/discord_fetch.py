"""Download dello storico del canale Discord via REST API (token di un BOT).

Due modalità di accesso:
  * BOT (DISCORD_BOT_TOKEN): il bot deve essere nel server con "View Channel" +
    "Read Message History" e l'intent "MESSAGE CONTENT" attivo.
  * ACCOUNT (DISCORD_USER_TOKEN, creato da `python -m chento login`): legge ciò che vede il tuo
    account. Automatizzare un account utente è contro i Termini di Discord e può portare al ban:
    il client resta in sola lettura e rallenta le richieste per ridurre il rischio.
"""
from __future__ import annotations

import time
from pathlib import Path

import requests

from .config import CONFIG, Config
from .db import Store

API = "https://discord.com/api/v10"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


class DiscordClient:
    def __init__(self, cfg: Config = CONFIG):
        if not (cfg.discord_token or cfg.user_token):
            raise SystemExit(
                "Nessuna credenziale Discord. Esegui `python -m chento login` (account personale) "
                "oppure imposta DISCORD_BOT_TOKEN, e riprova."
            )
        self.cfg = cfg
        self.user_mode = not cfg.discord_token
        self.s = requests.Session()
        if self.user_mode:
            self.s.headers.update({"Authorization": cfg.user_token, "User-Agent": USER_AGENT})
        else:
            self.s.headers.update({
                "Authorization": f"Bot {cfg.discord_token}",
                "User-Agent": "ChentoTracker (https://github.com, 1.0)",
            })
        self.page_delay = 1.5 if self.user_mode else 0.0

    def _get(self, path: str, **params):
        while True:
            r = self.s.get(f"{API}{path}", params=params, timeout=30)
            if r.status_code == 429:
                time.sleep(float(r.json().get("retry_after", 1)) + 0.25)
                continue
            if r.status_code == 401:
                raise SystemExit("401: credenziale non valida o scaduta. Rifai `python -m chento login`.")
            if r.status_code == 403:
                who = "il tuo account" if self.user_mode else "il bot"
                raise SystemExit(f"403: {who} non ha accesso al canale (permessi o non è nel server).")
            r.raise_for_status()
            return r.json()

    def messages(self, channel_id: str, before: str | None = None, after: str | None = None, limit: int = 100):
        params = {"limit": limit}
        if before:
            params["before"] = before
        if after:
            params["after"] = after
        return self._get(f"/channels/{channel_id}/messages", **params)

    def iter_history(self, channel_id: str, max_messages: int | None = None):
        """Itera dal più recente al più vecchio."""
        before, n = None, 0
        while True:
            batch = self.messages(channel_id, before=before)
            if not batch:
                return
            for m in batch:
                yield m
                n += 1
                if max_messages and n >= max_messages:
                    return
            before = batch[-1]["id"]
            time.sleep(self.page_delay)

    def me(self) -> dict:
        return self._get("/users/@me")

    def download(self, url: str, dest: Path) -> Path | None:
        if dest.exists():
            return dest
        try:
            r = self.s.get(url, timeout=60)
            r.raise_for_status()
        except requests.RequestException:
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)
        return dest


def normalize(raw: dict, client: DiscordClient | None, attachments_dir: Path) -> dict:
    author = raw.get("author", {})
    atts = []
    for a in raw.get("attachments", []):
        item = {"url": a["url"], "filename": a["filename"], "content_type": a.get("content_type", "")}
        if client and item["content_type"].startswith("image"):
            p = client.download(a["url"], attachments_dir / f"{raw['id']}_{a['filename']}")
            item["local_path"] = str(p) if p else None
        atts.append(item)
    for e in raw.get("embeds", []):
        img = (e.get("image") or e.get("thumbnail") or {}).get("url")
        if img:
            atts.append({"url": img, "filename": "embed", "content_type": "image/embed"})
    content = raw.get("content", "")
    for e in raw.get("embeds", []):
        content += "\n" + " ".join(x for x in (e.get("title"), e.get("description")) if x)
    return {
        "id": raw["id"],
        "channel_id": raw.get("channel_id"),
        "author_id": author.get("id"),
        "author_name": author.get("global_name") or author.get("username"),
        "ts": raw["timestamp"],
        "content": content.strip(),
        "attachments": atts,
        "reply_to": (raw.get("message_reference") or {}).get("message_id"),
    }


def is_target_author(m: dict, cfg: Config = CONFIG) -> bool:
    if cfg.author_id:
        return m.get("author_id") == cfg.author_id
    return cfg.author_name.lower() in (m.get("author_name") or "").lower()


def sync_history(store: Store, cfg: Config = CONFIG, max_messages: int | None = None) -> int:
    client = DiscordClient(cfg)
    n = 0
    for raw in client.iter_history(cfg.channel_id, max_messages):
        store.upsert_message(normalize(raw, client, cfg.attachments_dir))
        n += 1
    return n


def fetch_new(store: Store, client: DiscordClient, cfg: Config = CONFIG) -> list[dict]:
    """Messaggi successivi all'ultimo salvato (dal più vecchio al più nuovo)."""
    last = store.get_meta("last_seen_id")
    if last is None:
        newest = client.messages(cfg.channel_id, limit=1)
        if newest:
            store.set_meta("last_seen_id", newest[0]["id"])
        return []
    batch = client.messages(cfg.channel_id, after=last)
    batch.sort(key=lambda m: int(m["id"]))
    out = []
    for raw in batch:
        m = normalize(raw, client, cfg.attachments_dir)
        store.upsert_message(m)
        out.append(m)
        store.set_meta("last_seen_id", raw["id"])
    return out
