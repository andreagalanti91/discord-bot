"""Dataset DEMO **sintetico** per provare la pipeline senza accesso a Discord.

I messaggi sono generati qui (non sono messaggi reali di Chento) ma i livelli sono
costruiti su prezzi storici reali scaricati da Yahoo, quindi il backtest è realistico.
Ogni messaggio è marcato `demo=1` e l'autore è "Chento (DEMO)".
"""
from __future__ import annotations

import random
import time
from datetime import datetime, timezone

from .config import CONFIG
from .db import Store
from .market import Market, atr

UNIVERSE = [("BTC", "BTC-USD", 2), ("ETH", "ETH-USD", 2), ("SOL", "SOL-USD", 2),
            ("XAUUSD", "GC=F", 2), ("EURUSD", "EURUSD=X", 4), ("NAS100", "NQ=F", 1)]

SETUPS = [
    "retest dell'order block H4 dopo sweep della liquidità sotto i minimi",
    "FVG in discount ancora da mitigare, BOS confermato su H1",
    "breakout del range con retest pulito della resistenza diventata supporto",
    "doppio minimo su supporto daily + divergenza RSI",
    "rimbalzo sullo 0.618 di Fibonacci in confluenza con EMA 200",
    "CHoCH su 15m dopo presa di liquidità nella killzone di Londra",
    "trendline rotta e ritestata, volumi in aumento",
]
COMMENTS = [
    "Mercato laterale oggi, aspetto che prenda la liquidità prima di entrare.",
    "Occhio al CPI di domani, riduco l'esposizione.",
    "Struttura ancora rialzista su H4 finché tiene il supporto, cerco long in discount.",
    "Funding molto positivo e open interest in salita: possibile flush delle long.",
    "Settimana chiusa in profitto, ricordatevi di non overtradare.",
]


def _svg_chart(closes: list[float], entry: float, stop: float, tps: list[float]) -> str:
    w, h = 640, 320
    lo = min(closes + [stop] + tps) * 0.999
    hi = max(closes + [stop] + tps) * 1.001
    y = lambda v: h - (v - lo) / (hi - lo) * h  # noqa: E731
    pts = " ".join(f"{i * w / (len(closes) - 1):.1f},{y(c):.1f}" for i, c in enumerate(closes))
    lines = [f'<line x1="0" x2="{w}" y1="{y(entry):.1f}" y2="{y(entry):.1f}" stroke="#0A84FF" stroke-dasharray="6 4"/>',
             f'<line x1="0" x2="{w}" y1="{y(stop):.1f}" y2="{y(stop):.1f}" stroke="#FF453A" stroke-dasharray="6 4"/>']
    lines += [f'<line x1="0" x2="{w}" y1="{y(t):.1f}" y2="{y(t):.1f}" stroke="#30D158" stroke-dasharray="6 4"/>' for t in tps]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
            f'<rect width="100%" height="100%" fill="#1c1c1e"/>{"".join(lines)}'
            f'<polyline fill="none" stroke="#f2f2f7" stroke-width="1.6" points="{pts}"/>'
            f'<text x="12" y="22" fill="#8e8e93" font-family="-apple-system,sans-serif" font-size="13">DEMO · grafico sintetico</text></svg>')


def build(store: Store, market: Market, n_signals: int = 45, days: int = 55, seed: int = 7) -> int:
    rnd = random.Random(seed)
    store.clear()
    now = int(time.time()) // 3600 * 3600
    start = now - days * 86400
    series = {}
    for sym, yh, _ in UNIVERSE:
        c = market.candles(yh, start - 3 * 86400, now, "1h")
        if len(c) > 100:
            series[sym] = (yh, c)
    if not series:
        raise SystemExit("Impossibile scaricare prezzi da Yahoo per la demo.")
    CONFIG.attachments_dir.mkdir(parents=True, exist_ok=True)
    mid = 10**17
    msgs = []

    def add(ts: int, text: str, atts=None):
        nonlocal mid
        mid += rnd.randint(1000, 99999)
        msgs.append({"id": str(mid), "ts": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
                     "content": text, "attachments": atts or [], "author_id": "demo", "channel_id": CONFIG.channel_id,
                     "author_name": "Chento (DEMO)", "demo": 1})
        return str(mid)

    weights = [w for s, _, w in UNIVERSE if s in series]
    syms = [s for s, _, _ in UNIVERSE if s in series]
    for _ in range(n_signals):
        sym = rnd.choices(syms, weights)[0]
        yh, cs = series[sym]
        # orari tipici: apertura Londra e NY (UTC)
        i = rnd.randrange(30, len(cs) - 30)
        while datetime.fromtimestamp(cs[i].t, timezone.utc).hour not in (7, 8, 9, 13, 14, 15, 16) and rnd.random() < 0.85:
            i = rnd.randrange(30, len(cs) - 30)
        c = cs[i]
        a = atr(cs[i - 20:i + 1]) or c.c * 0.01
        trend = cs[i].c - cs[i - 24].c
        side = "long" if (trend > 0) ^ (rnd.random() < 0.3) else "short"
        d = 1 if side == "long" else -1
        entry = c.c - d * a * rnd.uniform(0, 0.4)
        stop = entry - d * a * rnd.uniform(1.2, 2.2)
        risk = abs(entry - stop)
        tps = [entry + d * risk * k for k in (1.0, 2.0, 3.2)][: rnd.choice([1, 2, 3, 3])]
        dec = 5 if sym == "EURUSD" else 2 if entry < 1000 else 0
        f = lambda v: f"{v:.{dec}f}"  # noqa: E731
        label = sym if sym in ("XAUUSD", "EURUSD", "NAS100") else f"${sym}"
        setup = rnd.choice(SETUPS)
        tf = rnd.choice(["H1", "H4", "15m", "H4"])
        text = (f"{'🟢 LONG' if d == 1 else '🔴 SHORT'} {label} ({tf})\n"
                f"Entry: {f(entry)}\nSL: {f(stop)}\n" + "\n".join(f"TP{k + 1}: {f(t)}" for k, t in enumerate(tps)) +
                f"\n\nSetup: {setup}.")
        atts = []
        if rnd.random() < 0.55:
            p = CONFIG.attachments_dir / f"demo_{mid + 1}.svg"
            p.write_text(_svg_chart([x.c for x in cs[i - 60:i + 1]], entry, stop, tps))
            atts = [{"url": "", "filename": p.name, "content_type": "image/svg+xml", "local_path": str(p)}]
        add(c.t + rnd.randint(0, 3000), text, atts)

        # follow-up realistici in base al prezzo successivo
        for j in range(i + 1, min(i + 120, len(cs))):
            x = cs[j]
            if (x.l <= stop) if d == 1 else (x.h >= stop):
                if rnd.random() < 0.6:
                    add(x.t + 600, rnd.choice([f"Stop preso su {sym}, fa parte del gioco.", f"SL hit {sym} ❌ next."]))
                break
            if (x.h >= tps[0]) if d == 1 else (x.l <= tps[0]):
                if rnd.random() < 0.75:
                    add(x.t + 900, f"TP1 preso su {sym} ✅ sposto SL a BE, trade risk free.")
                break
    for _ in range(12):
        add(start + rnd.randrange(0, days * 86400), rnd.choice(COMMENTS))
    msgs.sort(key=lambda m: m["ts"])
    for m in msgs:
        store.upsert_message(m)
    return len(msgs)
