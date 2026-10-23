"""Pipeline completa: messaggi → segnali → backtest (replica + derivata) → profilo → export dashboard."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import ai
from .alerts import build_alert
from .config import CONFIG, ROOT
from .db import Store
from .discord_fetch import is_target_author
from .market import Market
from .parser import parse_message
from .profiler import profile
from .strategies import run_all

DASHBOARD = ROOT / "dashboard"


def extract(store: Store, msg: dict, use_ai: bool = True, force: bool = False) -> dict:
    cached = store.signal(msg["id"])
    if cached and not force:
        return cached
    sig = parse_message(msg, CONFIG.default_asset_class).to_dict()
    if use_ai and (sig["kind"] != "comment" or sig["has_image"] or len(msg.get("content", "")) > 40):
        sig = ai.merge(sig, ai.enrich(msg, sig))
    sig["reply_to"] = msg.get("reply_to")
    store.save_signal(msg["id"], sig)
    return sig


def target_messages(store: Store) -> list[dict]:
    msgs = store.messages()
    if msgs and all(m.get("demo") for m in msgs):
        return msgs
    return [m for m in msgs if is_target_author(m)]


def _img_src(a: dict) -> str:
    p = a.get("local_path")
    if p and Path(p).exists():
        return os.path.relpath(p, DASHBOARD)
    return a.get("url", "")


def analyze(store: Store, market: Market, use_ai: bool = True, ensure_alerts: bool = True) -> dict:
    msgs = target_messages(store)
    signals = [extract(store, m, use_ai) for m in msgs]
    res = run_all(signals, market, CONFIG.risk_per_trade)
    prof = profile(msgs, signals, res["replica"]["trades"], res["updates"])

    rep_by = {t["msg_id"]: t for t in res["replica"]["trades"]}
    der_by = {t["msg_id"]: t for t in res["derived"]["trades"]}
    upd_parent = {u: e for e, us in res["updates"].items() for u in us}
    feed = []
    for m, s in zip(msgs, signals):
        feed.append({
            "id": m["id"], "ts": m["ts"], "author": m.get("author_name"), "text": m.get("content", ""),
            "images": [_img_src(a) for a in m["attachments"] if (a.get("content_type") or "").startswith("image")],
            "signal": s, "replica": rep_by.get(m["id"]), "derived": der_by.get(m["id"]),
            "parent": upd_parent.get(m["id"]),
        })

    if ensure_alerts:
        known = {a["msg_id"] for a in store.alerts()}
        for m, s in zip(msgs, signals):
            if m["id"] not in known:
                a = build_alert(m, s, res["replica"]["trades"], None)
                a["backfill"] = True
                store.save_alert(m["id"], m["ts"], a)

    rs, ds = res["replica"]["stats"], res["derived"]["stats"]
    data = {
        "generated": int(time.time()),
        "demo": bool(msgs and all(m.get("demo") for m in msgs)),
        "config": {"channel_id": CONFIG.channel_id, "risk_pct": CONFIG.risk_per_trade,
                   "ai": CONFIG.ai_enabled(), "author": CONFIG.author_id or CONFIG.author_name},
        "profile": prof,
        "replica": res["replica"],
        "derived": res["derived"],
        "comparison": compare(rs, ds),
        "feed": feed,
        "alerts": store.alerts()[:200],
    }
    return data


def compare(a: dict, b: dict) -> list[dict]:
    rows = [
        ("Trade eseguiti", "closed", "int"), ("Win rate", "win_rate", "pct"), ("R medio / trade", "avg_r", "r"),
        ("R totale", "total_r", "r"), ("Profit factor", "profit_factor", "x"), ("Max drawdown", "max_dd_r", "r"),
        ("Rendimento (1% rischio)", "return_pct", "pct"), ("Vincita media", "avg_win_r", "r"),
        ("Perdita media", "avg_loss_r", "r"), ("Durata media (h)", "avg_hold_h", "h"), ("Segnali saltati", "skipped", "int"),
    ]
    out = []
    for label, k, fmt in rows:
        va, vb = a.get(k), b.get(k)
        better = None
        if va is not None and vb is not None and k not in ("closed", "skipped", "avg_hold_h"):
            better = "b" if vb > va else "a" if va > vb else None
        out.append({"label": label, "a": va, "b": vb, "fmt": fmt, "better": better})
    return out


def export(data: dict) -> Path:
    DASHBOARD.mkdir(exist_ok=True)
    js = DASHBOARD / "data.js"
    js.write_text("window.CHENTO_DATA = " + json.dumps(data, ensure_ascii=False, default=str) + ";\n")
    (CONFIG.data_dir / "report.json").write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str))
    return js
