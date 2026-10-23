"""Estrazione rule-based di segnali di trading da testo libero (IT/EN).

Riconosce:
  * segnali di ingresso (simbolo, direzione, entry singola o range, SL, TP multipli, leva, timeframe)
  * aggiornamenti (TP preso, SL a breakeven, stop preso, chiusura, parziali)
  * commenti / analisi (keyword di stile: SMC, price action, indicatori ...)
Quando è disponibile una chiave Anthropic, `ai.enrich` affina il risultato e
legge anche gli screenshot dei grafici.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

NUM = r"(\d+(?:[.,]\d+)*(?:\s?[kK])?)"

CRYPTO = {
    "BTC", "ETH", "SOL", "XRP", "BNB", "ADA", "DOGE", "AVAX", "DOT", "LINK", "MATIC", "POL", "LTC",
    "TRX", "ATOM", "NEAR", "APT", "ARB", "OP", "SUI", "SEI", "INJ", "TIA", "PEPE", "SHIB", "WIF",
    "BONK", "FET", "RNDR", "RENDER", "TAO", "TON", "HBAR", "ICP", "FIL", "AAVE", "UNI", "MKR",
    "LDO", "JUP", "PYTH", "ENA", "ONDO", "STX", "IMX", "RUNE", "KAS", "FTM", "S", "HYPE", "TRUMP",
}
FIAT = {"EUR", "USD", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD"}
ALIASES = {
    "GOLD": "XAUUSD", "ORO": "XAUUSD", "XAU": "XAUUSD", "SILVER": "XAGUSD", "ARGENTO": "XAGUSD",
    "NAS100": "NAS100", "NASDAQ": "NAS100", "US100": "NAS100", "NQ": "NAS100", "USTEC": "NAS100",
    "US30": "US30", "DOW": "US30", "DJ30": "US30", "SPX": "SPX500", "SP500": "SPX500", "US500": "SPX500",
    "ES": "SPX500", "DAX": "GER40", "GER40": "GER40", "DE40": "GER40", "OIL": "USOIL", "WTI": "USOIL",
    "USOIL": "USOIL", "PETROLIO": "USOIL", "BITCOIN": "BTC", "ETHEREUM": "ETH", "SOLANA": "SOL",
}
YAHOO = {
    "XAUUSD": "GC=F", "XAGUSD": "SI=F", "NAS100": "NQ=F", "US30": "YM=F", "SPX500": "ES=F",
    "GER40": "^GDAXI", "USOIL": "CL=F",
}

LONG_WORDS = r"\b(long|buy|compra(?:re)?|acquist[oa]|rialzist[ao]|bullish|longare|go long)\b"
SHORT_WORDS = r"\b(short|sell|vend(?:i|ere|ita)|ribassist[ao]|bearish|shortare|go short)\b"

STYLE_TAGS = {
    "smc_ict": [r"order ?block", r"\bob\b", r"\bfvg\b", r"fair value gap", r"imbalance", r"liquidit",
                r"\bbos\b", r"\bchoch\b", r"break of structure", r"premium", r"discount", r"\bict\b",
                r"\bsmc\b", r"sweep", r"stop hunt", r"mitigation", r"breaker", r"\bote\b", r"killzone"],
    "price_action": [r"support", r"support[oi]", r"resisten", r"breakout", r"rottura", r"retest",
                     r"trend ?line", r"trendline", r"canale", r"channel", r"triang", r"wedge", r"cuneo",
                     r"flag", r"bandiera", r"double (?:top|bottom)", r"doppio (?:massimo|minimo)",
                     r"testa e spalle", r"head and shoulders", r"range", r"pullback", r"engulfing",
                     r"pin ?bar", r"doji", r"higher low", r"lower high", r"massimi crescenti"],
    "indicators": [r"\brsi\b", r"\bmacd\b", r"\bema\b", r"\bsma\b", r"\bma ?\d+", r"media mobile",
                   r"\bvwap\b", r"bollinger", r"stocastic", r"stoch", r"ichimoku", r"divergen",
                   r"\badx\b", r"\batr\b", r"supertrend"],
    "fibonacci": [r"fib", r"0[.,]618", r"0[.,]786", r"golden pocket", r"ritracciament", r"retracement",
                  r"estension", r"extension"],
    "wyckoff": [r"wyckoff", r"accumul", r"distribu", r"spring", r"upthrust", r"\butad\b"],
    "elliott": [r"elliott", r"onda \d", r"wave \d", r"impulsiv", r"correttiv[ao] abc"],
    "volume_orderflow": [r"volum", r"order ?flow", r"footprint", r"delta", r"open interest", r"\boi\b",
                         r"funding", r"liquidation", r"heatmap", r"\bpoc\b", r"volume profile"],
    "macro_news": [r"\bcpi\b", r"\bfomc\b", r"\bfed\b", r"powell", r"\bnfp\b", r"tassi", r"inflazion",
                   r"news", r"notizi", r"earnings", r"trimestral", r"etf", r"halving"],
}

TF_RE = re.compile(r"\b(1|3|5|15|30|45)\s?(m|min)\b|\b(1|2|4|6|8|12)\s?(h|ore|hr)\b|\b(d|1d|daily|giornaliero|w|1w|weekly|settimanale)\b|\b(h1|h4|m15|m5|m30|d1|w1)\b", re.I)


def parse_number(s: str) -> float | None:
    s = s.strip().replace(" ", "")
    mult = 1.0
    if s[-1:] in "kK":
        mult, s = 1000.0, s[:-1]
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        parts = s.split(",")
        s = s.replace(",", "") if all(len(p) == 3 for p in parts[1:]) and len(parts[0]) <= 3 else s.replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        return float(s) * mult
    except ValueError:
        return None


@dataclass
class Signal:
    msg_id: str
    ts: str
    kind: str = "comment"         # entry | update | comment
    symbol: str | None = None
    yahoo: str | None = None
    asset_class: str | None = None
    side: str | None = None       # long | short
    entry: list[float] = field(default_factory=list)   # 1 valore o [low, high]
    stop: float | None = None
    targets: list[float] = field(default_factory=list)
    leverage: float | None = None
    timeframe: str | None = None
    update: str | None = None     # tp_hit | sl_to_be | sl_hit | close | partial | sl_moved
    update_level: float | None = None
    tags: dict[str, int] = field(default_factory=dict)
    has_image: bool = False
    confidence: float = 0.0
    source: str = "rules"
    notes: str = ""

    def entry_price(self) -> float | None:
        return sum(self.entry) / len(self.entry) if self.entry else None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["entry_price"] = self.entry_price()
        d["rr"] = planned_rr(self)
        return d


def planned_rr(s: Signal) -> float | None:
    e = s.entry_price()
    if e is None or s.stop is None or not s.targets or e == s.stop:
        return None
    return round(abs(s.targets[-1] - e) / abs(e - s.stop), 2)


def resolve_symbol(token: str, default_asset: str = "crypto") -> tuple[str, str, str] | None:
    """Ritorna (simbolo canonico, ticker Yahoo, asset class)."""
    t = token.upper().lstrip("$#").replace("/", "").replace("-", "").replace(".P", "")
    t = re.sub(r"(PERP|\.P)$", "", t)
    t = ALIASES.get(t, t)
    if t in YAHOO:
        cls = "commodity" if t in ("XAUUSD", "XAGUSD", "USOIL") else "index"
        return t, YAHOO[t], cls
    if len(t) == 6 and t[:3] in FIAT and t[3:] in FIAT:
        return t, f"{t}=X", "forex"
    for quote in ("USDT", "USDC", "BUSD", "USD"):
        base = t[: -len(quote)]
        if t.endswith(quote) and base and (base in CRYPTO or quote != "USD"):
            return f"{base}USDT", f"{base}-USD", "crypto"
    if t in CRYPTO:
        return f"{t}USDT", f"{t}-USD", "crypto"
    if re.fullmatch(r"[A-Z]{1,5}", t) and token.startswith("$"):
        if default_asset == "crypto":
            return f"{t}USDT", f"{t}-USD", "crypto"
        return t, t, "stock"
    return None


SYMBOL_RE = re.compile(
    r"(\$[A-Za-z]{1,10}|#[A-Za-z]{2,10}|\b[A-Z]{2,10}/?(?:USDT|USDC|USD|BUSD|PERP)\b|\b[A-Z]{6}\b|"
    r"\b(?:" + "|".join(sorted(CRYPTO | set(ALIASES), key=len, reverse=True)) + r")\b)",
    re.I,
)


def find_symbol(text: str, default_asset: str) -> tuple[str, str, str] | None:
    for m in SYMBOL_RE.finditer(text):
        tok = m.group(0)
        # le parole comuni brevi (es. "S", "OP") devono essere maiuscole o con $
        bare = tok.upper().lstrip("$#")
        if bare in {"S", "OP", "ES", "NQ", "DOW", "OIL", "ORO"} and not (tok.startswith(("$", "#")) or tok.isupper()):
            continue
        r = resolve_symbol(tok, default_asset)
        if r:
            return r
    return None


def _levels(pattern: str, text: str) -> list[float]:
    out: list[float] = []
    for m in re.finditer(pattern, text, re.I):
        nums = re.findall(NUM, m.group("v"))
        out += [v for v in (parse_number(n) for n in nums) if v is not None]
    return out


def parse_message(msg: dict, default_asset: str = "crypto") -> Signal:
    text = msg.get("content") or ""
    low = text.lower()
    sig = Signal(msg_id=msg["id"], ts=msg["ts"])
    sig.has_image = any((a.get("content_type") or "").startswith("image") for a in msg.get("attachments", []))

    for style, pats in STYLE_TAGS.items():
        c = sum(len(re.findall(p, low)) for p in pats)
        if c:
            sig.tags[style] = c

    sym = find_symbol(text, default_asset)
    if sym:
        sig.symbol, sig.yahoo, sig.asset_class = sym

    if re.search(LONG_WORDS, low):
        sig.side = "long"
    elif re.search(SHORT_WORDS, low):
        sig.side = "short"

    tf = TF_RE.search(text)
    if tf:
        sig.timeframe = tf.group(0).lower().replace(" ", "")

    sep = r"\s*(?:[:=@]|is|a|at|zona|area|zone)?\s*"
    sig.entry = _levels(rf"(?:\b(?:entry|entrata|ingresso|ep|entra(?:ta)?|buy zone|sell zone|zona d'?ingresso|zona|area|limit)\b|@){sep}(?P<v>{NUM}(?:\s*(?:-|–|/|to|a)\s*{NUM})?)", text)[:2]
    stops = _levels(rf"\b(?:sl|stop ?loss|stoploss|stop|invalidation|invalidazione)\b{sep}(?P<v>{NUM})", text)
    sig.stop = stops[0] if stops else None
    sig.targets = _levels(rf"\b(?:tp|target|tg|take ?profit|obiettiv[oi])(?:\s?\d(?!\d))?\b{sep}(?P<v>{NUM}(?:(?:\s*(?:,|/|-|e|and)\s*|\s+){NUM})*)", text)
    lev = re.search(r"\b(?:x\s?(\d{1,3})|(\d{1,3})\s?x)\b|\bleva\s*(\d{1,3})", low)
    if lev:
        sig.leverage = float(next(g for g in lev.groups() if g))

    upd = None
    # lo spostamento a BE ha priorità: è l'azione operativa (il TP preso è informativo)
    if re.search(r"(sl|stop)\s*(a|al|to|in|on)\s*(be|b/e|break ?even|pareggio|entry)\b|\bbreak ?even\b|risk ?free", low):
        upd = "sl_to_be"
    elif re.search(r"\b(tp\s?\d?|target\s?\d?)\s*(hit|preso|raggiunt|colpit|centrat|done|✅)|\bpres[oi] (il )?tp", low):
        upd = "tp_hit"
    elif re.search(r"(sl|stop)\s*(hit|preso|colpito|toccato)|stopped out|stoppat", low):
        upd = "sl_hit"
    elif re.search(r"\b(chiud[oiae]|chiuso|close[d]?|exit|uscit[oa]|out)\b", low) and not sig.entry:
        upd = "close"
    elif re.search(r"\bparzial|\bpartial|secure profit|prendo profitt", low):
        upd = "partial"
    elif re.search(r"(sposto|move[d]?|alzo|abbasso|trail)\w*\s*(lo |the )?(sl|stop)", low):
        upd = "sl_moved"
    if upd:
        sig.update = upd
        lv = re.findall(NUM, low)
        if upd == "sl_moved" and lv:
            sig.update_level = parse_number(lv[-1])

    if sig.symbol and sig.side and (sig.entry or sig.stop or sig.targets) and not upd:
        sig.kind = "entry"
    elif upd:
        sig.kind = "update"
    elif sig.symbol and sig.side and re.search(r"\b(entr|apro|open|aperto|ingresso|market|a mercato|now|ora)\w*", low):
        sig.kind = "entry"  # ingresso a mercato senza livelli
    sig.confidence = _confidence(sig)
    _sanity(sig)
    return sig


def _confidence(s: Signal) -> float:
    if s.kind == "entry":
        return round(min(1.0, 0.3 + 0.2 * bool(s.entry) + 0.25 * bool(s.stop) + 0.25 * bool(s.targets)), 2)
    if s.kind == "update":
        return 0.6 if s.symbol else 0.4
    return 0.0


def _sanity(s: Signal) -> None:
    """Corregge errori tipici: direzione incoerente coi livelli, entry senza direzione."""
    _fix_scale(s)
    e = s.entry_price()
    if e is None:
        return
    if s.stop is not None and s.side is None:
        s.side = "long" if s.stop < e else "short"
    if s.stop is not None and s.side == "long" and s.stop > e:
        s.notes += "SL sopra entry su long: livelli incoerenti. "
        s.confidence = min(s.confidence, 0.3)
    if s.stop is not None and s.side == "short" and s.stop < e:
        s.notes += "SL sotto entry su short: livelli incoerenti. "
        s.confidence = min(s.confidence, 0.3)
    if s.targets and s.side:
        good = [t for t in s.targets if (t > e if s.side == "long" else t < e)]
        if len(good) != len(s.targets):
            s.notes += "Scartati target dal lato sbagliato. "
        s.targets = sorted(good, reverse=(s.side == "short"))


def _fix_scale(s: Signal) -> None:
    """"62.000" in formato europeo viene letto come 62.0: riallinea i livelli fuori scala di x1000."""
    levels = s.entry + s.targets + ([s.stop] if s.stop else [])
    if len(levels) < 2:
        return
    ref = sorted(levels)[len(levels) // 2]

    def fix(v: float) -> float:
        if v and 500 <= ref / v <= 2000:
            return v * 1000
        return v

    s.entry = [fix(v) for v in s.entry]
    s.targets = [fix(v) for v in s.targets]
    if s.stop:
        s.stop = fix(s.stop)
