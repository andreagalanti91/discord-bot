"""Archivio SQLite di messaggi, segnali estratti e alert."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    channel_id TEXT,
    author_id TEXT,
    author_name TEXT,
    ts TEXT,
    content TEXT,
    attachments TEXT,      -- JSON: [{url, filename, local_path, content_type}]
    reply_to TEXT,
    demo INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS signals (
    msg_id TEXT PRIMARY KEY,
    data TEXT              -- JSON del segnale estratto (vedi parser.Signal)
);
CREATE TABLE IF NOT EXISTS alerts (
    msg_id TEXT PRIMARY KEY,
    ts TEXT,
    data TEXT
);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def upsert_message(self, m: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO messages VALUES (?,?,?,?,?,?,?,?,?)",
            (
                m["id"], m.get("channel_id"), m.get("author_id"), m.get("author_name"),
                m["ts"], m.get("content", ""), json.dumps(m.get("attachments", [])),
                m.get("reply_to"), int(m.get("demo", 0)),
            ),
        )
        self.conn.commit()

    def messages(self, author_filter=None) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM messages ORDER BY ts").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["attachments"] = json.loads(d["attachments"] or "[]")
            if author_filter is None or author_filter(d):
                out.append(d)
        return out

    def save_signal(self, msg_id: str, data: dict) -> None:
        self.conn.execute("INSERT OR REPLACE INTO signals VALUES (?,?)", (msg_id, json.dumps(data)))
        self.conn.commit()

    def signal(self, msg_id: str) -> dict | None:
        r = self.conn.execute("SELECT data FROM signals WHERE msg_id=?", (msg_id,)).fetchone()
        return json.loads(r[0]) if r else None

    def save_alert(self, msg_id: str, ts: str, data: dict) -> None:
        self.conn.execute("INSERT OR REPLACE INTO alerts VALUES (?,?,?)", (msg_id, ts, json.dumps(data)))
        self.conn.commit()

    def alerts(self) -> list[dict]:
        rows = self.conn.execute("SELECT data FROM alerts ORDER BY ts DESC").fetchall()
        return [json.loads(r[0]) for r in rows]

    def get_meta(self, k: str, default: str | None = None) -> str | None:
        r = self.conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r[0] if r else default

    def set_meta(self, k: str, v: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, v))
        self.conn.commit()

    def clear(self) -> None:
        for t in ("messages", "signals", "alerts", "meta"):
            self.conn.execute(f"DELETE FROM {t}")
        self.conn.commit()
