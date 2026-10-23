from chento.backtest import Rules, link_updates, simulate, stats
from chento.market import Candle, to_epoch
from chento.parser import parse_message


def msg(text, mid="1", ts="2026-01-01T10:00:00+00:00", **kw):
    return {"id": mid, "ts": ts, "content": text, "attachments": [], **kw}


def test_full_signal_european_numbers():
    s = parse_message(msg("LONG $BTC entry 62.000-62.500 SL 60800 TP1 63500 TP2 65000 x10 (4h) order block"))
    assert (s.kind, s.symbol, s.side) == ("entry", "BTCUSDT", "long")
    assert s.entry == [62000, 62500] and s.stop == 60800 and s.targets == [63500, 65000]
    assert s.leverage == 10 and s.timeframe == "4h" and "smc_ict" in s.tags


def test_forex_and_gold():
    s = parse_message(msg("EURUSD sell entry 1,0850 sl 1,0880 tp 1,0790"))
    assert (s.symbol, s.yahoo, s.side, s.entry, s.stop, s.targets) == ("EURUSD", "EURUSD=X", "short", [1.085], 1.088, [1.079])
    g = parse_message(msg("XAUUSD buy @ 2345.5 sl 2338 tp 2360"))
    assert (g.yahoo, g.entry, g.targets) == ("GC=F", [2345.5], [2360])


def test_updates():
    assert parse_message(msg("TP1 preso su BTC ✅ sposto SL a BE")).update == "sl_to_be"
    assert parse_message(msg("Stop preso su SOL")).update == "sl_hit"
    assert parse_message(msg("bel retest della trendline")).kind == "comment"


def test_wrong_side_targets_dropped():
    s = parse_message(msg("BTC long entry 100 sl 90 tp 95 120"))
    assert s.targets == [120]


class FakeMarket:
    def __init__(self, candles):
        self.c = candles

    def candles(self, yahoo, start, end, interval=None):
        return [c for c in self.c if start <= c.t <= end]


def series(t0, rows):
    return [Candle(t0 + i * 3600, *r) for i, r in enumerate(rows)]


SIG = {"msg_id": "1", "ts": "2026-01-01T10:00:00+00:00", "symbol": "BTCUSDT", "yahoo": "BTC-USD",
       "side": "long", "entry_price": 100.0, "stop": 90.0, "targets": [110.0, 120.0], "kind": "entry"}


def test_simulate_tp_then_be():
    t0 = to_epoch(SIG["ts"])
    m = FakeMarket(series(t0, [(101, 102, 99, 100), (100, 111, 99, 110), (110, 112, 99, 100), (100, 101, 80, 85)]))
    rep = simulate(SIG, [], m, Rules("r", split="equal"))
    # metà a TP1 (+0.5R) e metà allo stop (-0.5R)
    assert rep["tp_hit"] == 1 and rep["outcome"] == "breakeven" and abs(rep["r"]) < 1e-9
    der = simulate(SIG, [], m, Rules("d", split="half_first", be_after_tp1=True))
    assert der["r"] == 0.5 and der["outcome"] == "win"


def test_stop_first_when_same_candle():
    t0 = to_epoch(SIG["ts"])
    m = FakeMarket(series(t0, [(100, 125, 85, 100)]))
    assert simulate(SIG, [], m, Rules("r"))["r"] == -1


def test_chento_close_update_applied():
    t0 = to_epoch(SIG["ts"])
    m = FakeMarket(series(t0, [(100, 101, 99, 100), (105, 106, 104, 105), (105, 106, 104, 105)]))
    up = {"msg_id": "2", "ts": "2026-01-01T11:30:00+00:00", "kind": "update", "update": "close", "symbol": "BTCUSDT"}
    links = link_updates([SIG, up], 168)
    assert links["1"] == [up]
    r = simulate(SIG, links["1"], m, Rules("r"))
    assert r["exits"][-1]["why"] == "chento_close" and r["r"] == 0.5


def test_stats():
    trades = [{"ts": "a", "outcome": "win", "r": 2}, {"ts": "b", "outcome": "loss", "r": -1},
              {"ts": "c", "outcome": "skipped", "r": 0}]
    s = stats(trades)
    assert s["win_rate"] == 50 and s["total_r"] == 1 and s["profit_factor"] == 2 and s["skipped"] == 1


def test_import_discordchatexporter(tmp_path, monkeypatch):
    import json

    from chento import importer
    from chento.db import Store
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "chart.png").write_bytes(b"png")
    export = {"channel": {"id": "c1"}, "messages": [
        {"id": "10", "type": "Default", "timestamp": "2026-01-01T10:00:00+00:00", "content": "LONG BTC entry 100 sl 90 tp 120",
         "author": {"id": "42", "name": "chento", "nickname": "Chento"},
         "attachments": [{"url": "media/chart.png", "fileName": "chart.png"}], "embeds": [], "reference": None},
        {"id": "11", "type": "Reply", "timestamp": "2026-01-01T12:00:00+00:00", "content": "sl a be",
         "author": {"id": "42", "name": "chento"}, "attachments": [], "embeds": [], "reference": {"messageId": "10"}},
    ]}
    f = tmp_path / "export.json"
    f.write_text(json.dumps(export))
    monkeypatch.setattr(importer.CONFIG, "data_dir", tmp_path / "data")
    store = Store(tmp_path / "data" / "db.sqlite")
    n, authors = importer.import_export(f, store)
    msgs = store.messages()
    assert n == 2 and list(authors.values()) == [2]
    assert msgs[0]["attachments"][0]["content_type"] == "image/png" and msgs[0]["attachments"][0]["local_path"]
    assert msgs[1]["reply_to"] == "10"


def test_client_auth_modes():
    from chento.config import Config
    from chento.discord_fetch import DiscordClient
    u = DiscordClient(Config(discord_token="", user_token="abc"))
    assert u.user_mode and u.s.headers["Authorization"] == "abc" and u.page_delay > 0
    b = DiscordClient(Config(discord_token="xyz", user_token=""))
    assert not b.user_mode and b.s.headers["Authorization"] == "Bot xyz"
