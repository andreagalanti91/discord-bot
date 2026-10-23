"""Alert per ogni nuovo messaggio di Chento: segnale strutturato + contesto storico + verdetto Chento+."""
from __future__ import annotations

import time

import requests

from .config import CONFIG
from .market import Market
from .strategies import Learner, chase_ratio, derived_verdict

KIND_LABEL = {"entry": "NUOVO SEGNALE", "update": "AGGIORNAMENTO", "comment": "COMMENTO"}
UPDATE_LABEL = {
    "tp_hit": "Target raggiunto", "sl_to_be": "Stop a breakeven", "sl_hit": "Stop loss preso",
    "close": "Chiusura posizione", "partial": "Chiusura parziale", "sl_moved": "Stop spostato",
}


def build_alert(msg: dict, sig: dict, replica_trades: list[dict], market: Market | None) -> dict:
    learner = Learner()
    for t in replica_trades:
        if t["ts"] < sig["ts"]:
            learner.add(t)
    ctx = learner.context(sig)
    price = None
    if market and sig.get("yahoo"):
        try:
            price = market.last_price(sig["yahoo"])
        except Exception:  # dati di mercato best-effort
            price = None
    a = {
        "msg_id": msg["id"], "ts": msg["ts"], "created": int(time.time()),
        "kind": sig["kind"], "title": KIND_LABEL[sig["kind"]],
        "symbol": sig.get("symbol"), "side": sig.get("side"),
        "entry": sig.get("entry"), "stop": sig.get("stop"), "targets": sig.get("targets"),
        "rr": sig.get("rr"), "timeframe": sig.get("timeframe"), "price_now": price,
        "text": msg.get("content", ""), "has_image": sig.get("has_image"),
        "tags": sig.get("tags"), "context": ctx, "ai_analysis": sig.get("ai_analysis"),
        "setup": sig.get("setup"), "notes": sig.get("notes"),
    }
    if sig["kind"] == "entry":
        ok, reasons = derived_verdict(sig, ctx, price)
        a["verdict"] = "PRENDI" if ok else "SALTA"
        a["reasons"] = reasons
        e = sig.get("entry_price")
        if price and e:
            a["distance_pct"] = round((price - e) / e * 100, 2)
            a["chase"] = chase_ratio(sig, price)
        if e and sig.get("stop"):
            stop_pct = abs(e - sig["stop"]) / e * 100
            a["stop_pct"] = round(stop_pct, 2)
            # size suggerita: % del conto da impiegare per rischiare CONFIG.risk_per_trade
            a["position_pct"] = round(CONFIG.risk_per_trade / stop_pct * 100, 1)
    elif sig["kind"] == "update":
        a["update"] = UPDATE_LABEL.get(sig.get("update"), sig.get("update"))
    a["summary"] = summarize(a)
    return a


def summarize(a: dict) -> str:
    if a["kind"] == "entry":
        lv = []
        if a.get("entry"):
            lv.append("entry " + "–".join(f"{x:g}" for x in a["entry"]))
        if a.get("stop"):
            lv.append(f"SL {a['stop']:g}")
        if a.get("targets"):
            lv.append("TP " + " / ".join(f"{x:g}" for x in a["targets"]))
        s = f"{(a.get('side') or '?').upper()} {a.get('symbol') or '?'} · " + ", ".join(lv or ["a mercato"])
        if a.get("rr"):
            s += f" · R:R {a['rr']}"
        c = a["context"]
        if c["symbol_n"]:
            s += f" · storico {a['symbol']}: WR {c['symbol_wr']}% su {c['symbol_n']}"
        return s + f" → {a['verdict']}"
    if a["kind"] == "update":
        return f"{a.get('update')} {a.get('symbol') or ''}".strip()
    styles = ", ".join(a.get("tags") or {}) or "nessun setup riconosciuto"
    return f"Commento ({styles})"


def send_webhook(a: dict, url: str = CONFIG.alert_webhook) -> bool:
    if not url:
        return False
    color = {"PRENDI": 0x34C759, "SALTA": 0xFF9500}.get(a.get("verdict"), 0x0A84FF if a["kind"] == "update" else 0x8E8E93)
    fields = []
    if a["kind"] == "entry":
        fields += [
            {"name": "Verdetto Chento+", "value": f"**{a['verdict']}** — " + "; ".join(a["reasons"]), "inline": False},
            {"name": "Prezzo ora", "value": f"{a['price_now']:g}" if a.get("price_now") else "n/d", "inline": True},
            {"name": "Distanza entry", "value": f"{a['distance_pct']:+.2f}%" if a.get("distance_pct") is not None else "n/d", "inline": True},
            {"name": "Size suggerita", "value": f"{a['position_pct']}% del conto" if a.get("position_pct") else "n/d", "inline": True},
        ]
    if a.get("ai_analysis"):
        fields.append({"name": "Analisi", "value": a["ai_analysis"][:1000], "inline": False})
    payload = {"embeds": [{
        "title": f"{a['title']} · {a.get('symbol') or ''}".strip(" ·"),
        "description": a["summary"] + (f"\n\n> {a['text'][:500]}" if a.get("text") else ""),
        "color": color, "fields": fields, "timestamp": a["ts"],
    }]}
    try:
        r = requests.post(url, json=payload, timeout=15)
        return r.ok
    except requests.RequestException:
        return False


def console(a: dict) -> str:
    icon = {"PRENDI": "🟢", "SALTA": "🟠"}.get(a.get("verdict"), "🔵" if a["kind"] == "update" else "⚪")
    lines = [f"{icon} [{a['title']}] {a['summary']}"]
    if a.get("reasons"):
        lines.append("   motivi: " + "; ".join(a["reasons"]))
    if a.get("ai_analysis"):
        lines.append("   analisi: " + a["ai_analysis"])
    return "\n".join(lines)
