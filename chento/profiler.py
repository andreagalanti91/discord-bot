"""Profilo della strategia e dei comportamenti ricorrenti a partire da messaggi, segnali e trade."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from statistics import mean, median
from zoneinfo import ZoneInfo

from .market import to_epoch
from .strategies import breakdown, session_of

TZ = ZoneInfo("Europe/Rome")
DAYS = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]
STYLE_LABEL = {
    "smc_ict": "Smart Money Concepts / ICT (order block, FVG, liquidità, BOS/CHoCH)",
    "price_action": "Price action classica (supporti/resistenze, breakout e retest, pattern)",
    "indicators": "Indicatori tecnici (RSI, EMA, MACD, VWAP...)",
    "fibonacci": "Ritracciamenti / estensioni di Fibonacci",
    "wyckoff": "Wyckoff (accumulo/distribuzione, spring, UTAD)",
    "elliott": "Onde di Elliott",
    "volume_orderflow": "Volumi / order flow / derivati (OI, funding, liquidazioni)",
    "macro_news": "Macro e news (CPI, FOMC, ETF...)",
}


def local(ts: str) -> datetime:
    return datetime.fromtimestamp(to_epoch(ts), TZ)


def _pct(a: int, b: int) -> float | None:
    return round(a / b * 100, 1) if b else None


def profile(messages: list[dict], signals: list[dict], replica: list[dict], updates: dict[str, list[str]]) -> dict:
    entries = [s for s in signals if s["kind"] == "entry"]
    upds = [s for s in signals if s["kind"] == "update"]
    by_id = {s["msg_id"]: s for s in signals}

    heat = [[0] * 24 for _ in range(7)]
    for m in messages:
        d = local(m["ts"])
        heat[d.weekday()][d.hour] += 1
    entry_hours = Counter(local(s["ts"]).hour for s in entries)

    first, last = (messages[0]["ts"], messages[-1]["ts"]) if messages else (None, None)
    days = max(1, (to_epoch(last) - to_epoch(first)) / 86400) if messages else 1

    styles = Counter()
    for s in signals:
        styles.update(s.get("tags") or {})
    style_total = sum(styles.values())
    style_mix = [{"key": k, "label": STYLE_LABEL[k], "pct": _pct(v, style_total)} for k, v in styles.most_common()]

    sym = Counter(s["symbol"] for s in entries if s.get("symbol"))
    cls = Counter(s.get("asset_class") for s in entries if s.get("asset_class"))
    sides = Counter(s.get("side") for s in entries if s.get("side"))
    tfs = Counter(s["timeframe"] for s in signals if s.get("timeframe"))

    sl_d = [abs(s["entry_price"] - s["stop"]) / s["entry_price"] * 100 for s in entries
            if s.get("entry_price") and s.get("stop")]
    rrs = [s["rr"] for s in entries if s.get("rr")]
    ntp = [len(s["targets"]) for s in entries if s.get("targets")]
    lev = [s["leverage"] for s in entries if s.get("leverage")]

    closed = [t for t in replica if t["outcome"] in ("win", "loss", "breakeven")]
    holds = [t["hold_h"] for t in closed if t.get("hold_h") is not None]
    hold_med = median(holds) if holds else None
    horizon = None
    if hold_med is not None:
        horizon = "scalping" if hold_med < 4 else "intraday" if hold_med < 24 else "swing" if hold_med < 24 * 10 else "position"

    be_after = sum(any(by_id[u]["update"] == "sl_to_be" for u in v if u in by_id) for v in updates.values())
    partial_after = sum(any(by_id[u]["update"] == "partial" for u in v if u in by_id) for v in updates.values())
    closes_after = sum(any(by_id[u]["update"] == "close" for u in v if u in by_id) for v in updates.values())

    reentries = 0
    last_by_sym: dict[str, int] = {}
    for s in entries:
        t = to_epoch(s["ts"])
        if s.get("symbol") in last_by_sym and t - last_by_sym[s["symbol"]] < 86400:
            reentries += 1
        last_by_sym[s.get("symbol")] = t

    # dopo una perdita pubblica di più o di meno? (revenge / tilt)
    gaps_after_loss, gaps_after_win = [], []
    srt = sorted(closed, key=lambda t: t["ts"])
    for a, b in zip(srt, srt[1:]):
        g = (to_epoch(b["ts"]) - to_epoch(a["ts"])) / 3600
        (gaps_after_loss if a["outcome"] == "loss" else gaps_after_win).append(g)

    # coerenza: TP dichiarati presi vs. verificati sul prezzo
    claimed_tp = [u for u in upds if u["update"] == "tp_hit"]
    claimed_sl = [u for u in upds if u["update"] == "sl_hit"]

    out = {
        "period": {"from": first, "to": last, "days": round(days, 1)},
        "activity": {
            "messages": len(messages),
            "with_images": sum(any((a.get("content_type") or "").startswith("image") for a in m["attachments"]) for m in messages),
            "entries": len(entries), "updates": len(upds),
            "comments": len(signals) - len(entries) - len(upds),
            "per_day": round(len(messages) / days, 2),
            "signals_per_week": round(len(entries) / days * 7, 2),
            "heatmap": heat,
            "top_entry_hours": [h for h, _ in entry_hours.most_common(3)],
        },
        "instruments": [{"key": k, "n": v} for k, v in sym.most_common(12)],
        "asset_classes": [{"key": k, "n": v} for k, v in cls.most_common()],
        "sides": {"long": sides.get("long", 0), "short": sides.get("short", 0)},
        "timeframes": [{"key": k, "n": v} for k, v in tfs.most_common(6)],
        "style_mix": style_mix,
        "risk": {
            "with_stop_pct": _pct(sum(1 for s in entries if s.get("stop")), len(entries)),
            "with_targets_pct": _pct(sum(1 for s in entries if s.get("targets")), len(entries)),
            "avg_stop_pct": round(mean(sl_d), 2) if sl_d else None,
            "avg_planned_rr": round(mean(rrs), 2) if rrs else None,
            "median_planned_rr": round(median(rrs), 2) if rrs else None,
            "avg_targets": round(mean(ntp), 1) if ntp else None,
            "avg_leverage": round(mean(lev), 1) if lev else None,
        },
        "management": {
            "be_after_entry_pct": _pct(be_after, len(entries)),
            "partials_pct": _pct(partial_after, len(entries)),
            "manual_close_pct": _pct(closes_after, len(entries)),
            "reentries_24h": reentries,
            "median_hold_h": round(hold_med, 1) if hold_med is not None else None,
            "horizon": horizon,
            "avg_gap_after_loss_h": round(mean(gaps_after_loss), 1) if gaps_after_loss else None,
            "avg_gap_after_win_h": round(mean(gaps_after_win), 1) if gaps_after_win else None,
            "claimed_tp": len(claimed_tp), "claimed_sl": len(claimed_sl),
        },
        "by_symbol": breakdown(replica, lambda t: t["symbol"]),
        "by_session": breakdown(replica, lambda t: session_of(t["ts"])),
        "by_side": breakdown(replica, lambda t: t["side"]),
        "by_weekday": breakdown(replica, lambda t: DAYS[local(t["ts"]).weekday()]),
    }
    out["fingerprint"] = fingerprint(out)
    out["insights"] = insights(out)
    return out


def fingerprint(p: dict) -> dict:
    style = p["style_mix"][0]["label"] if p["style_mix"] else "non determinabile dal testo"
    second = p["style_mix"][1]["label"] if len(p["style_mix"]) > 1 else None
    cls = p["asset_classes"][0]["key"] if p["asset_classes"] else "n/d"
    top = ", ".join(i["key"] for i in p["instruments"][:3]) or "n/d"
    L, S = p["sides"]["long"], p["sides"]["short"]
    bias = "prevalentemente long" if L > 1.5 * S else "prevalentemente short" if S > 1.5 * L else "bilanciato long/short"
    tf = p["timeframes"][0]["key"] if p["timeframes"] else None
    hz = p["management"]["horizon"] or "n/d"
    summary = (
        f"Trader {hz}, asset class principale {cls}; strumenti più operati: {top}. Bias {bias.replace('prevalentemente ', '')}. "
        f"Approccio dominante: {style}" + (f", con elementi di {second.split(' (')[0].lower()}" if second else "") + ". "
    )
    if tf:
        summary += f"Timeframe più citato: {tf}. "
    r = p["risk"]
    if r["avg_planned_rr"]:
        summary += f"R:R pianificato medio {r['avg_planned_rr']} con ~{r['avg_targets'] or 1} target; stop medio {r['avg_stop_pct']}% dal prezzo. "
    m = p["management"]
    if m["be_after_entry_pct"]:
        summary += f"Sposta lo stop a breakeven nel {m['be_after_entry_pct']}% dei trade."
    return {"style": style, "secondary": second, "asset_class": cls, "top_symbols": top, "bias": bias,
            "timeframe": tf, "horizon": hz, "summary": summary.strip()}


def insights(p: dict) -> list[dict]:
    """Pattern ricorrenti espressi in frasi, con tono (pos/neg/neutral)."""
    out = []
    a, r, m = p["activity"], p["risk"], p["management"]
    if a["top_entry_hours"]:
        hrs = ", ".join(f"{h:02d}:00" for h in a["top_entry_hours"])
        out.append({"tone": "neutral", "text": f"Gli ingressi si concentrano attorno a {hrs} (ora italiana)."})
    best = [b for b in p["by_session"] if b["n"] >= 5]
    if best:
        b = max(best, key=lambda x: x["avg_r"] or -9)
        w = min(best, key=lambda x: x["avg_r"] or 9)
        if (b["avg_r"] or 0) > 0:
            out.append({"tone": "pos", "text": f"Sessione migliore: {b['key']} ({b['avg_r']:+.2f}R medi su {b['n']} trade)."})
        if w["key"] != b["key"] and (w["avg_r"] or 0) < 0:
            out.append({"tone": "neg", "text": f"Sessione peggiore: {w['key']} ({w['avg_r']:+.2f}R medi) — candidata da filtrare."})
    syms = [s for s in p["by_symbol"] if s["n"] >= 4]
    for s in sorted(syms, key=lambda x: x["avg_r"] or 0)[:2]:
        if (s["avg_r"] or 0) < 0:
            out.append({"tone": "neg", "text": f"{s['key']}: expectancy negativa ({s['avg_r']:+.2f}R su {s['n']} trade)."})
    for s in sorted(syms, key=lambda x: -(x["avg_r"] or 0))[:2]:
        if (s["avg_r"] or 0) > 0:
            out.append({"tone": "pos", "text": f"{s['key']}: il suo strumento più redditizio ({s['avg_r']:+.2f}R, WR {s['win_rate']}%)."})
    if r["with_stop_pct"] is not None and r["with_stop_pct"] < 80:
        out.append({"tone": "neg", "text": f"Solo il {r['with_stop_pct']}% dei segnali indica uno stop loss esplicito."})
    if r["avg_planned_rr"] and r["avg_planned_rr"] < 1.5:
        out.append({"tone": "neg", "text": f"R:R pianificato basso ({r['avg_planned_rr']}): serve un win rate alto per essere profittevoli."})
    if m["reentries_24h"]:
        out.append({"tone": "neutral", "text": f"{m['reentries_24h']} re-entry sullo stesso simbolo entro 24h (tende a riprovare il setup)."})
    if m["avg_gap_after_loss_h"] and m["avg_gap_after_win_h"] and m["avg_gap_after_loss_h"] < 0.6 * m["avg_gap_after_win_h"]:
        out.append({"tone": "neg", "text": f"Dopo una perdita torna a operare più in fretta ({m['avg_gap_after_loss_h']}h vs {m['avg_gap_after_win_h']}h): possibile revenge trading."})
    if a["with_images"]:
        out.append({"tone": "neutral", "text": f"{a['with_images']} messaggi su {a['messages']} contengono grafici/screenshot."})
    L, S = p["sides"]["long"], p["sides"]["short"]
    sides = {b["key"]: b for b in p["by_side"]}
    if "long" in sides and "short" in sides:
        lg, sh = sides["long"], sides["short"]
        if (lg["avg_r"] or 0) * (sh["avg_r"] or 0) < 0:
            good, bad = (lg, sh) if (lg["avg_r"] or 0) > 0 else (sh, lg)
            out.append({"tone": "neutral", "text": f"Rende sui {good['key']} ({good['avg_r']:+.2f}R) ma perde sui {bad['key']} ({bad['avg_r']:+.2f}R)."})
    elif L + S:
        out.append({"tone": "neutral", "text": f"Opera solo {('long' if L else 'short')}."})
    return out
