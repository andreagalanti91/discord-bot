"""Dati OHLC storici da Yahoo Finance (crypto, forex, indici, commodity, azioni) con cache su disco."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from .config import CONFIG

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
# limiti storici Yahoo per intervallo (giorni)
LIMITS = [("15m", 59), ("1h", 729), ("1d", 100000)]


@dataclass
class Candle:
    t: int      # epoch secondi (apertura)
    o: float
    h: float
    l: float
    c: float


def to_epoch(ts: str) -> int:
    return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp())


def pick_interval(start: int) -> str:
    age_days = (time.time() - start) / 86400
    for iv, lim in LIMITS:
        if age_days < lim:
            return iv
    return "1d"


class Market:
    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir or (CONFIG.data_dir / "candles")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "Mozilla/5.0"
        self.mem: dict[tuple, list[Candle]] = {}

    def candles(self, yahoo: str, start: int, end: int, interval: str | None = None) -> list[Candle]:
        interval = interval or pick_interval(start)
        step = {"15m": 900, "1h": 3600, "1d": 86400}[interval]
        start -= start % step
        end = min(end, int(time.time()))
        key = (yahoo, interval, start // 86400, end // 3600)
        if key in self.mem:
            return self.mem[key]
        f = self.cache_dir / f"{yahoo.replace('=', '_').replace('^', '')}_{interval}_{start}_{end // 3600}.json"
        if f.exists():
            data = json.loads(f.read_text())
        else:
            data = self._download(yahoo, start, end, interval)
            # non mettere in cache finestre ancora aperte
            if data and end < time.time() - 3600:
                f.write_text(json.dumps(data))
        out = [Candle(*row) for row in data if start <= row[0] <= end]
        self.mem[key] = out
        return out

    def _download(self, yahoo: str, start: int, end: int, interval: str) -> list[list]:
        for attempt in range(3):
            try:
                r = self.s.get(URL.format(sym=yahoo), params={
                    "period1": start, "period2": end + 1, "interval": interval, "includePrePost": "true",
                }, timeout=30)
                if r.status_code == 404:
                    return []
                r.raise_for_status()
                res = r.json()["chart"]["result"]
                if not res:
                    return []
                res = res[0]
                ts = res.get("timestamp") or []
                q = res["indicators"]["quote"][0]
                rows = []
                for i, t in enumerate(ts):
                    o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
                    if None in (o, h, l, c):
                        continue
                    rows.append([t, o, h, l, c])
                return rows
            except (requests.RequestException, KeyError, ValueError):
                time.sleep(2 ** attempt)
        return []

    def last_price(self, yahoo: str) -> float | None:
        now = int(time.time())
        c = self.candles(yahoo, now - 2 * 86400, now, "15m")
        return c[-1].c if c else None


def atr(candles: list[Candle], n: int = 14) -> float | None:
    if len(candles) < n + 1:
        return None
    trs = [max(c.h - c.l, abs(c.h - p.c), abs(c.l - p.c)) for p, c in zip(candles[-n - 1:-1], candles[-n:])]
    return sum(trs) / n
