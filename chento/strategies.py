"""Due strategie applicate agli stessi segnali:

1. **Replica Chento** — copia 1:1: stessi ingressi, stessi SL/TP, uscite parziali
   equidistribuite sui target, applica i suoi aggiornamenti (BE, chiusure, parziali).

2. **Chento+ (derivata)** — stessi segnali ma con:
   * filtri appresi *walk-forward* (solo trade già chiusi prima del segnale, niente lookahead):
     - salta simboli con expectancy storica negativa (>= 5 trade)
     - salta la sessione oraria con expectancy negativa (>= 8 trade)
     - salta i setup con R:R pianificato < 1.5
     - salta i segnali "inseguiti" (prezzo già oltre il 50% della distanza entry→TP1)
     - salta i segnali a bassa confidenza di parsing
   * gestione: 50% a TP1 + SL a breakeven, resto sull'ultimo target;
     se mancano target, TP implicito a 2R; se manca lo SL, 1.2×ATR.
"""
from __future__ import annotations

from collections import defaultdict

from .backtest import Rules, link_updates, simulate, stats
from .market import Market, to_epoch

REPLICA = Rules(name="Replica Chento", split="equal", be_after_tp1=False, follow_updates=True, atr_mult=1.5)
DERIVED = Rules(name="Chento+", split="half_first", be_after_tp1=True, follow_updates=True,
                atr_mult=1.2, default_target_r=2.0)

MIN_RR = 1.5
SESSIONS = [(0, 7, "Asia"), (7, 12, "Londra"), (12, 16, "NY open"), (16, 21, "NY pm"), (21, 24, "Asia")]


def session_of(ts: str) -> str:
    h = (to_epoch(ts) // 3600) % 24
    return next(name for a, b, name in SESSIONS if a <= h < b)


class Learner:
    """Statistiche incrementali sulle performance già note della replica."""

    def __init__(self):
        self.by_symbol = defaultdict(list)
        self.by_session = defaultdict(list)
        self.by_side = defaultdict(list)

    def add(self, trade: dict) -> None:
        if trade["outcome"] not in ("win", "loss", "breakeven"):
            return
        self.by_symbol[trade["symbol"]].append(trade["r"])
        self.by_session[session_of(trade["ts"])].append(trade["r"])
        self.by_side[trade["side"]].append(trade["r"])

    @staticmethod
    def _exp(xs: list[float]) -> float | None:
        return sum(xs) / len(xs) if xs else None

    def context(self, sig: dict) -> dict:
        sym = self.by_symbol.get(sig.get("symbol"), [])
        ses = self.by_session.get(session_of(sig["ts"]), [])
        side = self.by_side.get(sig.get("side"), [])
        wr = lambda xs: round(sum(x > 0.05 for x in xs) / len(xs) * 100, 1) if xs else None  # noqa: E731
        return {
            "symbol_n": len(sym), "symbol_exp": self._exp(sym), "symbol_wr": wr(sym),
            "session": session_of(sig["ts"]), "session_n": len(ses), "session_exp": self._exp(ses),
            "session_wr": wr(ses),
            "side_n": len(side), "side_exp": self._exp(side), "side_wr": wr(side),
        }


def chase_ratio(sig: dict, price: float | None) -> float | None:
    """Quanto il prezzo si è già mosso verso TP1 (0 = all'entry, 1 = a TP1)."""
    e, tps = sig.get("entry_price"), sig.get("targets") or []
    if price is None or e is None or not tps or tps[0] == e:
        return None
    return (price - e) / (tps[0] - e)


def derived_verdict(sig: dict, ctx: dict, price_now: float | None) -> tuple[bool, list[str]]:
    reasons, ok = [], True
    if sig.get("confidence", 0) < 0.5:
        ok = False
        reasons.append("segnale incompleto/ambiguo")
    rr = sig.get("rr")
    if rr is not None and rr < MIN_RR:
        ok = False
        reasons.append(f"R:R {rr} < {MIN_RR}")
    if ctx["symbol_n"] >= 5 and ctx["symbol_exp"] is not None and ctx["symbol_exp"] < -0.05:
        ok = False
        reasons.append(f"{sig.get('symbol')} storicamente negativo ({ctx['symbol_exp']:+.2f}R su {ctx['symbol_n']})")
    if ctx["session_n"] >= 8 and ctx["session_exp"] is not None and ctx["session_exp"] < -0.05:
        ok = False
        reasons.append(f"sessione {ctx['session']} negativa ({ctx['session_exp']:+.2f}R)")
    ch = chase_ratio(sig, price_now)
    if ch is not None and ch > 0.5:
        ok = False
        reasons.append(f"prezzo già al {ch * 100:.0f}% verso TP1 (inseguimento)")
    if ok:
        reasons.append("supera tutti i filtri")
    return ok, reasons


def run_all(signals: list[dict], market: Market, risk_pct: float = 1.0) -> dict:
    signals = sorted(signals, key=lambda s: s["ts"])
    updates = link_updates(signals, REPLICA.max_hold_h)
    entries = [s for s in signals if s["kind"] == "entry"]
    learner = Learner()
    pending: list[dict] = []        # trade replica non ancora "noti" al learner
    replica, derived = [], []
    for sig in entries:
        t0 = to_epoch(sig["ts"])
        # rende visibili al learner solo i trade chiusi prima di questo segnale
        still = []
        for tr in pending:
            close_t = tr["exits"][-1]["t"] if tr.get("exits") else None
            if close_t is not None and close_t <= t0 and tr["outcome"] != "open":
                learner.add(tr)
            else:
                still.append(tr)
        pending = still

        ups = updates.get(sig["msg_id"], [])
        rep = simulate(sig, ups, market, REPLICA)
        replica.append(rep)
        if rep.get("exits"):
            pending.append(rep)

        ctx = learner.context(sig)
        first = market.candles(sig["yahoo"], t0, t0 + 3 * 3600) if sig.get("yahoo") else []
        ok, reasons = derived_verdict(sig, ctx, first[0].o if first else None)
        if ok:
            der = simulate(sig, ups, market, DERIVED)
        else:
            der = {"msg_id": sig["msg_id"], "ts": sig["ts"], "symbol": sig.get("symbol"),
                   "side": sig.get("side"), "strategy": DERIVED.name, "outcome": "skipped", "r": 0.0}
        der["reasons"] = reasons
        der["context"] = ctx
        derived.append(der)

    return {
        "replica": {"trades": replica, "stats": stats(replica, risk_pct)},
        "derived": {"trades": derived, "stats": stats(derived, risk_pct)},
        "updates": {k: [u["msg_id"] for u in v] for k, v in updates.items()},
    }


def breakdown(trades: list[dict], key) -> list[dict]:
    groups = defaultdict(list)
    for t in trades:
        if t["outcome"] in ("win", "loss", "breakeven"):
            groups[key(t)].append(t)
    rows = []
    for k, ts in groups.items():
        s = stats(ts)
        rows.append({"key": k, "n": s["closed"], "win_rate": s["win_rate"], "avg_r": s["avg_r"],
                     "total_r": s["total_r"]})
    return sorted(rows, key=lambda r: -r["n"])
