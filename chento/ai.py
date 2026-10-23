"""Arricchimento opzionale con Claude: legge testo + screenshot dei grafici e restituisce
il segnale strutturato e una breve analisi. Attivo solo se ANTHROPIC_API_KEY è presente."""
from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path

from .config import CONFIG

SYSTEM = (
    "Sei un analista di trading. Ricevi un messaggio Discord di un trader (testo ed eventuali "
    "screenshot di grafici). Estrai il segnale operativo se presente, altrimenti classifica il "
    "messaggio come aggiornamento o commento. Dai grafici leggi strumento, timeframe, livelli "
    "disegnati (entry, stop, target) e il setup tecnico. Non inventare livelli che non sono "
    "scritti o chiaramente disegnati: usa null. L'analisi va scritta in italiano, 2-4 frasi, "
    "concreta: setup, punti di forza, rischi."
)

NUM_OR_NULL = {"type": ["number", "null"]}
SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["entry", "update", "comment"]},
        "symbol": {"type": ["string", "null"], "description": "es. BTCUSDT, EURUSD, XAUUSD, NAS100, AAPL"},
        "side": {"type": ["string", "null"], "enum": ["long", "short", None]},
        "entry": {"type": "array", "items": {"type": "number"}},
        "stop": NUM_OR_NULL,
        "targets": {"type": "array", "items": {"type": "number"}},
        "timeframe": {"type": ["string", "null"]},
        "update": {"type": ["string", "null"],
                   "enum": ["tp_hit", "sl_to_be", "sl_hit", "close", "partial", "sl_moved", None]},
        "update_level": NUM_OR_NULL,
        "setup": {"type": "string", "description": "nome breve del setup, es. 'retest order block H4'"},
        "chart_reading": {"type": "string", "description": "cosa mostra il grafico, vuoto se non ci sono immagini"},
        "analysis": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["kind", "symbol", "side", "entry", "stop", "targets", "timeframe", "update",
                 "update_level", "setup", "chart_reading", "analysis", "confidence"],
    "additionalProperties": False,
}

_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()
    return _client


def _image_blocks(msg: dict, limit: int = 3) -> list[dict]:
    blocks = []
    for a in msg.get("attachments", []):
        p = a.get("local_path")
        if not p or not Path(p).exists():
            continue
        mt = a.get("content_type") or mimetypes.guess_type(p)[0] or "image/png"
        if mt not in ("image/png", "image/jpeg", "image/gif", "image/webp"):
            continue
        data = base64.standard_b64encode(Path(p).read_bytes()).decode()
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": mt, "data": data}})
        if len(blocks) >= limit:
            break
    return blocks


def enrich(msg: dict, rules_sig: dict) -> dict | None:
    """Ritorna i campi estratti da Claude, o None se l'AI non è disponibile / rifiuta."""
    if not CONFIG.ai_enabled():
        return None
    import anthropic

    content = _image_blocks(msg) + [{
        "type": "text",
        "text": f"Messaggio ({msg['ts']}):\n{msg.get('content') or '(solo immagine)'}\n\n"
                f"Estrazione rule-based (può essere incompleta): {json.dumps(rules_sig, ensure_ascii=False)}",
    }]
    try:
        resp = _get_client().beta.messages.create(
            model=CONFIG.anthropic_model,
            max_tokens=4000,
            system=SYSTEM,
            messages=[{"role": "user", "content": content}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.RateLimitError:
        return None
    except anthropic.APIStatusError as e:
        print(f"[ai] errore API {e.status_code}: {e.message}")
        return None
    except anthropic.APIConnectionError:
        return None
    if resp.stop_reason == "refusal":
        return None
    text = next((b.text for b in resp.content if b.type == "text"), None)
    try:
        return json.loads(text) if text else None
    except json.JSONDecodeError:
        return None


def merge(sig: dict, ai: dict | None) -> dict:
    """Completa i campi mancanti della regola con quelli dell'AI (le regole hanno priorità sui numeri scritti)."""
    if not ai:
        return sig
    from .parser import resolve_symbol

    out = dict(sig)
    out["source"] = "rules+ai"
    out["setup"] = ai.get("setup")
    out["chart_reading"] = ai.get("chart_reading")
    out["ai_analysis"] = ai.get("analysis")
    if sig["kind"] == "comment" and ai["kind"] != "comment":
        out["kind"] = ai["kind"]
    if not sig.get("symbol") and ai.get("symbol"):
        r = resolve_symbol(ai["symbol"], CONFIG.default_asset_class) or resolve_symbol("$" + ai["symbol"], CONFIG.default_asset_class)
        if r:
            out["symbol"], out["yahoo"], out["asset_class"] = r
    for k in ("side", "stop", "timeframe", "update", "update_level"):
        if out.get(k) in (None, "") and ai.get(k) not in (None, ""):
            out[k] = ai[k]
    for k in ("entry", "targets"):
        if not out.get(k) and ai.get(k):
            out[k] = ai[k]
    if out.get("entry"):
        out["entry_price"] = sum(out["entry"]) / len(out["entry"])
    e, s, t = out.get("entry_price"), out.get("stop"), out.get("targets")
    out["rr"] = round(abs(t[-1] - e) / abs(e - s), 2) if e and s and t and e != s else out.get("rr")
    out["confidence"] = max(sig.get("confidence", 0), min(1.0, float(ai.get("confidence") or 0)))
    return out
