from __future__ import annotations

import asyncio
import logging
import signal

from config import ConfigurationError, Settings
from mt5_client import MT5Client
from telegram_bot import build_application
from trading_engine import TradingEngine


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


async def async_main() -> None:
    try:
        settings = Settings.from_env()
    except (ConfigurationError, ValueError) as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)
    client = MT5Client(settings)
    engine = TradingEngine(settings=settings, client=client)
    application = build_application(settings, engine)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, engine.stop)
        except NotImplementedError:  # Windows event loops may not support it.
            pass

    await application.initialize()
    await application.start()
    if application.updater is None:
        raise RuntimeError("Telegram updater is unavailable")
    await application.updater.start_polling(drop_pending_updates=True)

    logger.info("Telegram polling started")
    try:
        await engine.run()
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        logger.info("Application shutdown complete")


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
