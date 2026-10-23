"""Import di un export JSON di DiscordChatExporter (fatto in locale dall'utente con il proprio account).

Le credenziali restano sul PC dell'utente: qui arriva solo il file esportato.
Con l'opzione `--media` di DiscordChatExporter gli allegati sono file locali accanto al JSON.
"""
from __future__ import annotations

import json
import mimetypes
import shutil
from pathlib import Path

from .config import CONFIG
from .db import Store

IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def _attachment(a: dict, msg_id: str, base: Path) -> dict:
    url = a.get("url", "")
    name = a.get("fileName") or Path(url).name
    ctype = mimetypes.guess_type(name)[0] or ""
    item = {"url": url, "filename": name, "content_type": ctype}
    local = base / url if url and not url.startswith("http") else None
    if local and local.exists():
        dest = CONFIG.attachments_dir / f"{msg_id}_{local.name}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copyfile(local, dest)
        item["local_path"] = str(dest)
    return item


def import_export(path: Path, store: Store) -> tuple[int, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    channel = data.get("channel", {}).get("id")
    counts: dict[str, int] = {}
    names: dict[str, str] = {}
    n = 0
    for m in data.get("messages", []):
        if m.get("type") not in (None, "Default", "Reply"):
            continue
        author = m.get("author", {})
        content = m.get("content", "")
        for e in m.get("embeds", []):
            content += "\n" + " ".join(x for x in (e.get("title"), e.get("description")) if x)
        atts = [_attachment(a, m["id"], base) for a in m.get("attachments", [])]
        for e in m.get("embeds", []):
            img = (e.get("image") or e.get("thumbnail") or {}).get("url")
            if img and Path(img.split("?")[0]).suffix.lower() in IMG_EXT:
                atts.append(_attachment({"url": img}, m["id"], base))
        name = author.get("nickname") or author.get("name")
        store.upsert_message({
            "id": m["id"], "channel_id": channel, "author_id": author.get("id"), "author_name": name,
            "ts": m["timestamp"], "content": content.strip(), "attachments": atts,
            "reply_to": (m.get("reference") or {}).get("messageId"),
        })
        aid = author.get("id")
        names.setdefault(aid, name)
        counts[aid] = counts.get(aid, 0) + 1
        n += 1
    authors = {f"{names[a]} ({a})": c for a, c in sorted(counts.items(), key=lambda kv: -kv[1])}
    return n, authors
