from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load the external .env file located beside this module. Secrets are never
# stored in Python source files. Existing platform environment variables win.
_ENV_FILE = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_ENV_FILE, override=False)


class ConfigurationError(ValueError):
    """Raised when a required or invalid environment setting is found."""



def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(f"Missing required environment variable: {name}")
    return value



def _int(name: str, default: int, minimum: Optional[int] = None) -> int:
    raw = os.getenv(name)
    value = default if raw is None or raw.strip() == "" else int(raw)
    if minimum is not None and value < minimum:
        raise ConfigurationError(f"{name} must be >= {minimum}")
    return value



def _float(name: str, default: float, minimum: Optional[float] = None) -> float:
    raw = os.getenv(name)
    value = default if raw is None or raw.strip() == "" else float(raw)
    if minimum is not None and value < minimum:
        raise ConfigurationError(f"{name} must be >= {minimum}")
    return value



def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    """Runtime configuration for the MT5 scalper."""

    mt5_login: int
    mt5_password: str
    mt5_server: str
    mt5_terminal_path: Optional[str]
    telegram_bot_token: str
    telegram_chat_id: int
    symbols: tuple[str, ...]
    lot_size: float
    trigger_points: int
    take_profit_points: int
    stop_loss_points: int
    max_allowed_spread_points: int
    max_open_positions: int
    cooldown_ms: int
    deviation: int
    magic_number: int
    poll_interval_ms: int
    dry_run: bool
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        symbols_raw = os.getenv("TRADING_SYMBOLS", "EURUSD").strip()
        symbols = tuple(s.strip() for s in symbols_raw.split(",") if s.strip())
        if not symbols:
            raise ConfigurationError("TRADING_SYMBOLS must contain at least one symbol")

        chat_id = _required("TELEGRAM_CHAT_ID")
        try:
            parsed_chat_id = int(chat_id)
        except ValueError as exc:
            raise ConfigurationError("TELEGRAM_CHAT_ID must be an integer") from exc

        return cls(
            mt5_login=_int("MT5_LOGIN", 0, 1),
            mt5_password=_required("MT5_PASSWORD"),
            mt5_server=_required("MT5_SERVER"),
            mt5_terminal_path=os.getenv("MT5_TERMINAL_PATH") or None,
            telegram_bot_token=_required("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=parsed_chat_id,
            symbols=symbols,
            lot_size=_float("LOT_SIZE", 0.01, 0.00001),
            trigger_points=_int("TRIGGER_POINTS", 1, 1),
            take_profit_points=_int("TAKE_PROFIT_POINTS", 5, 1),
            stop_loss_points=_int("STOP_LOSS_POINTS", 10, 1),
            max_allowed_spread_points=_int("MAX_ALLOWED_SPREAD_POINTS", 30, 0),
            max_open_positions=_int("MAX_OPEN_POSITIONS", 1, 1),
            cooldown_ms=_int("COOLDOWN_MS", 250, 0),
            deviation=_int("DEVIATION", 20, 0),
            magic_number=_int("MAGIC_NUMBER", 260819, 1),
            poll_interval_ms=_int("POLL_INTERVAL_MS", 50, 10),
            dry_run=_bool("DRY_RUN", True),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
