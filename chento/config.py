"""Configurazione letta da variabili d'ambiente (o da un file .env nella root)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


@dataclass
class Config:
    discord_token: str = os.getenv("DISCORD_BOT_TOKEN", "")
    channel_id: str = os.getenv("DISCORD_CHANNEL_ID", "1547586761515860069")
    guild_id: str = os.getenv("DISCORD_GUILD_ID", "1042855255089623100")
    # Autore da tracciare: ID numerico (preferito) oppure parte del nome.
    author_id: str = os.getenv("CHENTO_AUTHOR_ID", "")
    author_name: str = os.getenv("CHENTO_AUTHOR_NAME", "chento")
    alert_webhook: str = os.getenv("ALERT_WEBHOOK_URL", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5")
    use_ai: bool = os.getenv("CHENTO_USE_AI", "auto") != "0"
    # Classe di default per ticker ambigui: crypto | stock
    default_asset_class: str = os.getenv("CHENTO_DEFAULT_ASSET", "crypto")
    risk_per_trade: float = float(os.getenv("CHENTO_RISK_PCT", "1.0"))
    max_hold_hours: int = int(os.getenv("CHENTO_MAX_HOLD_H", "168"))
    fill_window_hours: int = int(os.getenv("CHENTO_FILL_WINDOW_H", "48"))
    poll_seconds: int = int(os.getenv("CHENTO_POLL_S", "30"))
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("CHENTO_DATA_DIR", ROOT / "data")))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "chento.sqlite"

    @property
    def attachments_dir(self) -> Path:
        return self.data_dir / "attachments"

    def ai_enabled(self) -> bool:
        has_creds = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
        return self.use_ai and has_creds


CONFIG = Config()
