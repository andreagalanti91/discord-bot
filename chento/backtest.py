"""Simulazione candle-by-candle dei segnali e statistiche di performance.

Convenzioni (conservative):
  * se nella stessa candela vengono toccati SL e TP, si assume prima lo SL;
  * entry con livello -> ordine limit (o stop-entry se il livello è "oltre" il prezzo);
    entry senza livello -> a mercato all'apertura della candela successiva;
  * segnale senza SL -> SL implicito a k*ATR(14), marcato `implied_stop`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .market import Candle, Market, atr, to_epoch


@dataclass
class Rules:
    name: str
    split: str = "equal"            # equal | half_first  (50% a TP1, resto sull'ultimo TP)
    be_after_tp1: bool = False
    follow_updates: bool = True     # applica gli aggiornamenti di Chento (BE, chiusure, parziali)
    atr_mult: float = 1.5           # SL implicito se manca
    default_target_r: float | None = None  # TP implicito (in R) se mancano target
    max_hold_h: int = 168
    fill_window_h: int = 48


def link_updates(signals: list[dict], max_hold_h: int) -> dict[str, list[dict]]:
    """Associa ad ogni entry gli update successivi sullo stesso simbolo (o in reply)."""
    entries = [s for s in signals if s["kind"] == "entry"]
    out: dict[str, list[dict]] = {e["msg_id"]: [] for e in entries}
    for u in (s for s in signals if s["kind"] == "update"):
        ut = to_epoch(u["ts"])
        cands = [e for e in entries if 0 < ut - to_epoch(e["ts"]) <= max_hold_h * 3600]
        target = None
        if u.get("reply_to"):
            target = next((e for e in cands if e["msg_id"] == u["reply_to"]), None)
        if target is None and u.get("symbol"):
            same = [e for e in cands if e["symbol"] == u["symbol"]]
            target = same[-1] if same else None
        if target is None and len(cands) == 1:
            target = cands[0]
        if target:
            out[target["msg_id"]].append(u)
    return out


def _fractions(n: int, split: str) -> list[float]:
    if n == 0:
        return []
    if split == "half_first" and n > 1:
        return [0.5] + [0.0] * (n - 2) + [0.5]
    return [1.0 / n] * n


def simulate(sig: dict, updates: list[dict], market: Market, rules: Rules) -> dict:
    t0 = to_epoch(sig["ts"])
    side = sig.get("side")
    base = {"msg_id": sig["msg_id"], "ts": sig["ts"], "symbol": sig.get("symbol"), "side": side,
            "strategy": rules.name}
    if not sig.get("yahoo") or side not in ("long", "short"):
        return {**base, "outcome": "invalid", "r": 0.0}
    d = 1 if side == "long" else -1
    hist = market.candles(sig["yahoo"], t0 - 40 * 3600, t0)
    candles = market.candles(sig["yahoo"], t0, t0 + (rules.fill_window_h + rules.max_hold_h) * 3600)
    candles = [c for c in candles if c.t >= t0 - 60]
    if not candles:
        return {**base, "outcome": "no_data", "r": 0.0}

    # ---- fill
    px = sig.get("entry_price")
    fill_i, fill = None, None
    if px is None:
        fill_i, fill = 0, candles[0].o
    else:
        stop_entry = (px - candles[0].o) * d > candles[0].o * 0.0005
        for i, c in enumerate(candles):
            if c.t - t0 > rules.fill_window_h * 3600:
                break
            if not stop_entry and (c.l <= px if d == 1 else c.h >= px):
                fill_i, fill = i, (min(px, c.o) if d == 1 else max(px, c.o))
                break
            if stop_entry and (c.h >= px if d == 1 else c.l <= px):
                fill_i, fill = i, (max(px, c.o) if d == 1 else min(px, c.o))
                break
    if fill_i is None:
        return {**base, "outcome": "not_filled", "r": 0.0}

    # ---- stop & target
    stop, implied = sig.get("stop"), False
    if stop is None or (fill - stop) * d <= 0:
        a = atr(hist + candles[:fill_i]) or fill * 0.01
        stop, implied = fill - d * rules.atr_mult * a, True
    risk = abs(fill - stop)
    targets = [t for t in (sig.get("targets") or []) if (t - fill) * d > 0]
    if not targets and rules.default_target_r:
        targets = [fill + d * rules.default_target_r * risk]
    fracs = _fractions(len(targets), rules.split)
    remaining = 1.0
    realized = 0.0          # in R, pesato per frazione
    exits: list[dict] = []
    mfe = mae = 0.0
    tp_idx = 0
    ups = sorted(updates, key=lambda u: u["ts"]) if rules.follow_updates else []
    ui = 0

    def close(frac: float, price: float, why: str, t: int):
        nonlocal remaining, realized
        frac = min(frac, remaining)
        if frac <= 1e-9:
            return
        realized += frac * (price - fill) * d / risk
        remaining -= frac
        exits.append({"t": t, "price": round(price, 8), "frac": round(frac, 3), "why": why})

    end_t = candles[fill_i].t + rules.max_hold_h * 3600
    last = candles[fill_i]
    for i in range(fill_i, len(candles)):
        c = candles[i]
        last = c
        if c.t > end_t:
            close(remaining, c.o, "max_hold", c.t)
            break
        while ui < len(ups) and to_epoch(ups[ui]["ts"]) <= c.t:
            u = ups[ui]
            ui += 1
            kind = u.get("update")
            if kind == "sl_to_be":
                stop = fill if (fill - stop) * d > 0 else stop
            elif kind == "sl_moved" and u.get("update_level"):
                lv = u["update_level"]
                if (c.o - lv) * d > 0:
                    stop = lv
            elif kind == "close":
                close(remaining, c.o, "chento_close", c.t)
            elif kind == "partial":
                close(remaining / 2, c.o, "chento_partial", c.t)
        if remaining <= 1e-9:
            break
        hi, lo = (c.h, c.l) if d == 1 else (c.l, c.h)
        mfe = max(mfe, (hi - fill) * d / risk)
        mae = min(mae, (lo - fill) * d / risk)
        if (c.l <= stop) if d == 1 else (c.h >= stop):
            gap = c.o if ((c.o < stop) if d == 1 else (c.o > stop)) and i > fill_i else stop
            close(remaining, gap, "stop" if abs(stop - fill) > 1e-12 else "breakeven", c.t)
            break
        while tp_idx < len(targets) and ((c.h >= targets[tp_idx]) if d == 1 else (c.l <= targets[tp_idx])):
            last_tp = tp_idx == len(targets) - 1
            close(remaining if last_tp else fracs[tp_idx], targets[tp_idx], f"tp{tp_idx + 1}", c.t)
            if tp_idx == 0 and rules.be_after_tp1:
                stop = fill
            tp_idx += 1
        if remaining <= 1e-9:
            break

    status = "closed"
    if remaining > 1e-9:
        # ancora aperto: valorizzato a mercato
        realized += remaining * (last.c - fill) * d / risk
        status = "open"
    r = round(realized, 3)
    outcome = status if status == "open" else ("win" if r > 0.05 else "loss" if r < -0.05 else "breakeven")
    return {
        **base,
        "outcome": outcome,
        "r": r,
        "pct": round(r * risk / fill * 100, 3),
        "fill": round(fill, 8),
        "stop": round(stop, 8),
        "risk_pct": round(risk / fill * 100, 3),
        "implied_stop": implied,
        "targets": targets,
        "tp_hit": tp_idx,
        "exits": exits,
        "mfe_r": round(mfe, 2),
        "mae_r": round(mae, 2),
        "hold_h": round(((exits[-1]["t"] if exits else last.t) - candles[fill_i].t) / 3600, 1),
        "planned_rr": sig.get("rr"),
    }


def stats(trades: list[dict], risk_pct: float = 1.0) -> dict:
    done = [t for t in trades if t["outcome"] in ("win", "loss", "breakeven", "open")]
    closed = [t for t in done if t["outcome"] != "open"]
    wins = [t for t in closed if t["outcome"] == "win"]
    losses = [t for t in closed if t["outcome"] == "loss"]
    gross_w = sum(t["r"] for t in wins)
    gross_l = -sum(t["r"] for t in losses)
    eq_r, peak, dd, curve, eq_pct = 0.0, 0.0, 0.0, [], 100.0
    close_ts = lambda x: datetime.fromtimestamp(x["exits"][-1]["t"], timezone.utc).isoformat() if x.get("exits") else x["ts"]  # noqa: E731
    for t in sorted(closed, key=close_ts):
        eq_r += t["r"]
        eq_pct *= 1 + t["r"] * risk_pct / 100
        peak = max(peak, eq_r)
        dd = min(dd, eq_r - peak)
        curve.append({"ts": close_ts(t), "r": round(eq_r, 3), "equity": round(eq_pct, 2)})
    n = len(closed)
    return {
        "signals": len(trades),
        "filled": len(done),
        "closed": n,
        "open": len(done) - n,
        "not_filled": sum(t["outcome"] == "not_filled" for t in trades),
        "skipped": sum(t["outcome"] == "skipped" for t in trades),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": n - len(wins) - len(losses),
        "win_rate": round(len(wins) / n * 100, 1) if n else None,
        "avg_r": round(sum(t["r"] for t in closed) / n, 3) if n else None,
        "total_r": round(eq_r, 2),
        "profit_factor": round(gross_w / gross_l, 2) if gross_l else None,
        "max_dd_r": round(dd, 2),
        "avg_win_r": round(gross_w / len(wins), 2) if wins else None,
        "avg_loss_r": round(-gross_l / len(losses), 2) if losses else None,
        "return_pct": round(eq_pct - 100, 2),
        "avg_hold_h": round(sum(t.get("hold_h", 0) for t in closed) / n, 1) if n else None,
        "curve": curve,
    }
