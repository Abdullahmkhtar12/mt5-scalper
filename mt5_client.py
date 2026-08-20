from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from config import Settings
from strategy import Side, Tick

try:
    import MetaTrader5 as mt5
except ImportError:  # Allows unit tests and linting on non-MT5 hosts.
    mt5 = None

logger = logging.getLogger(__name__)


class MT5UnavailableError(RuntimeError):
    pass


class MT5OperationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Position:
    ticket: int
    symbol: str
    side: Side
    volume: float
    price_open: float
    profit: float
    time: int


@dataclass(frozen=True, slots=True)
class TradeResult:
    success: bool
    ticket: Optional[int]
    price: Optional[float]
    profit: Optional[float]
    retcode: Optional[int]
    message: str


class MT5Client:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.connected = False

    def _require_module(self) -> Any:
        if mt5 is None:
            raise MT5UnavailableError(
                "MetaTrader5 is unavailable. MT5 Python integration requires a compatible terminal host."
            )
        return mt5

    def connect(self) -> bool:
        api = self._require_module()
        kwargs = {
            "login": self.settings.mt5_login,
            "password": self.settings.mt5_password,
            "server": self.settings.mt5_server,
        }
        initialized = api.initialize(self.settings.mt5_terminal_path, **kwargs) if self.settings.mt5_terminal_path else api.initialize(**kwargs)
        if not initialized:
            self.connected = False
            logger.error("MT5 initialize failed: %s", api.last_error())
            return False

        for symbol in self.settings.symbols:
            if not api.symbol_select(symbol, True):
                logger.warning("Could not select symbol %s: %s", symbol, api.last_error())
        self.connected = True
        logger.info("Connected to MT5 server %s", self.settings.mt5_server)
        return True

    def ensure_connection(self) -> bool:
        api = self._require_module()
        if self.connected and api.terminal_info() is not None:
            return True
        self.disconnect()
        return self.connect()

    def disconnect(self) -> None:
        if mt5 is not None:
            try:
                mt5.shutdown()
            except Exception:  # pragma: no cover - defensive cleanup
                logger.exception("MT5 shutdown failed")
        self.connected = False

    def tick(self, symbol: str) -> Optional[Tick]:
        api = self._require_module()
        value = api.symbol_info_tick(symbol)
        if value is None:
            logger.warning("No tick received for %s: %s", symbol, api.last_error())
            return None
        return Tick(symbol=symbol, bid=float(value.bid), ask=float(value.ask), time_msc=int(value.time_msc))

    def point(self, symbol: str) -> float:
        api = self._require_module()
        info = api.symbol_info(symbol)
        if info is None or float(info.point) <= 0:
            raise MT5OperationError(f"Unable to read point size for {symbol}: {api.last_error()}")
        return float(info.point)

    def positions(self, magic_number: Optional[int] = None) -> list[Position]:
        api = self._require_module()
        raw_positions = api.positions_get()
        if raw_positions is None:
            return []
        result: list[Position] = []
        for item in raw_positions:
            if magic_number is not None and getattr(item, "magic", None) != magic_number:
                continue
            side = Side.BUY if int(item.type) == int(api.POSITION_TYPE_BUY) else Side.SELL
            result.append(
                Position(
                    ticket=int(item.ticket),
                    symbol=str(item.symbol),
                    side=side,
                    volume=float(item.volume),
                    price_open=float(item.price_open),
                    profit=float(item.profit),
                    time=int(item.time),
                )
            )
        return result

    def open_market_order(self, symbol: str, side: Side, volume: float, deviation: int, magic_number: int) -> TradeResult:
        api = self._require_module()
        info = api.symbol_info(symbol)
        current = api.symbol_info_tick(symbol)
        if info is None or current is None:
            return TradeResult(False, None, None, None, None, f"Missing symbol data: {api.last_error()}")

        order_type = api.ORDER_TYPE_BUY if side == Side.BUY else api.ORDER_TYPE_SELL
        price = float(current.ask if side == Side.BUY else current.bid)
        request = {
            "action": api.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
            "price": price,
            "deviation": int(deviation),
            "magic": int(magic_number),
            "comment": "tick-scalper",
            "type_time": api.ORDER_TIME_GTC,
            "type_filling": int(getattr(info, "filling_mode", api.ORDER_FILLING_IOC)),
        }
        result = api.order_send(request)
        if result is None:
            return TradeResult(False, None, None, None, None, f"order_send returned None: {api.last_error()}")

        success = int(result.retcode) in {int(api.TRADE_RETCODE_DONE), int(api.TRADE_RETCODE_PLACED), int(api.TRADE_RETCODE_DONE_PARTIAL)}
        message = str(getattr(result, "comment", ""))
        if not success:
            message = f"retcode={result.retcode}; {message}"
        return TradeResult(
            success=success,
            ticket=int(getattr(result, "order", 0) or getattr(result, "deal", 0)) or None,
            price=float(getattr(result, "price", price)) if success else None,
            profit=None,
            retcode=int(result.retcode),
            message=message,
        )

    def close_position(self, position: Position, deviation: int, magic_number: int) -> TradeResult:
        api = self._require_module()
        current = api.symbol_info_tick(position.symbol)
        if current is None:
            return TradeResult(False, None, None, None, None, f"Missing tick: {api.last_error()}")

        close_type = api.ORDER_TYPE_SELL if position.side == Side.BUY else api.ORDER_TYPE_BUY
        price = float(current.bid if position.side == Side.BUY else current.ask)
        request = {
            "action": api.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": position.volume,
            "type": close_type,
            "position": position.ticket,
            "price": price,
            "deviation": int(deviation),
            "magic": int(magic_number),
            "comment": "tick-scalper-exit",
            "type_time": api.ORDER_TIME_GTC,
            "type_filling": int(getattr(api.symbol_info(position.symbol), "filling_mode", api.ORDER_FILLING_IOC)),
        }
        result = api.order_send(request)
        if result is None:
            return TradeResult(False, None, None, None, None, f"close order returned None: {api.last_error()}")
        success = int(result.retcode) in {int(api.TRADE_RETCODE_DONE), int(api.TRADE_RETCODE_PLACED), int(api.TRADE_RETCODE_DONE_PARTIAL)}
        return TradeResult(
            success=success,
            ticket=int(getattr(result, "deal", 0) or getattr(result, "order", 0)) or None,
            price=float(getattr(result, "price", price)) if success else None,
            profit=position.profit if success else None,
            retcode=int(result.retcode),
            message=str(getattr(result, "comment", "")),
        )

    def close_all_positions(self, magic_number: Optional[int] = None) -> list[TradeResult]:
        results: list[TradeResult] = []
        for position in self.positions(magic_number):
            results.append(self.close_position(position, self.settings.deviation, self.settings.magic_number))
        return results
