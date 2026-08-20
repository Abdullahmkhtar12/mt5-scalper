from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Optional

from config import Settings
from mt5_client import MT5Client, Position
from strategy import ExitDecision, Signal, Side, Tick, TickScalpingStrategy

logger = logging.getLogger(__name__)
Notifier = Callable[[str], Awaitable[None]]


class TradingEngine:
    def __init__(self, settings: Settings, client: MT5Client, notifier: Optional[Notifier] = None):
        self.settings = settings
        self.client = client
        self.strategy = TickScalpingStrategy(
            trigger_points=settings.trigger_points,
            take_profit_points=settings.take_profit_points,
            stop_loss_points=settings.stop_loss_points,
        )
        self.max_spread_points = settings.max_allowed_spread_points
        self.notifier = notifier
        self.paused = False
        self._stop_event = asyncio.Event()
        self._trade_lock = asyncio.Lock()
        self._last_trade_at: dict[str, float] = {}

    def stop(self) -> None:
        self._stop_event.set()

    async def _notify(self, text: str) -> None:
        if self.notifier is None:
            return
        try:
            await self.notifier(text)
        except Exception:
            logger.exception("Notification failed")

    async def run(self) -> None:
        logger.info("Trading engine started; dry_run=%s", self.settings.dry_run)
        reconnect_delay = 1.0
        while not self._stop_event.is_set():
            try:
                connected = await asyncio.to_thread(self.client.ensure_connection)
                if not connected:
                    await asyncio.sleep(reconnect_delay)
                    reconnect_delay = min(reconnect_delay * 2, 30.0)
                    continue
                reconnect_delay = 1.0
                await self._process_cycle()
            except Exception:
                logger.exception("Trading cycle failed; reconnecting")
                self.client.connected = False
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 30.0)
            await asyncio.sleep(self.settings.poll_interval_ms / 1000)

        await asyncio.to_thread(self.client.disconnect)
        logger.info("Trading engine stopped")

    async def _process_cycle(self) -> None:
        positions = await asyncio.to_thread(self.client.positions, self.settings.magic_number)
        await self._manage_positions(positions)

        if self.paused:
            return

        for symbol in self.settings.symbols:
            tick = await asyncio.to_thread(self.client.tick, symbol)
            if tick is None:
                continue
            point = await asyncio.to_thread(self.client.point, symbol)
            signal = self.strategy.evaluate_signal(tick, point)
            if signal is None:
                continue

            spread_points = (tick.ask - tick.bid) / point
            if spread_points > self.max_spread_points:
                logger.debug("Signal suppressed for %s because spread is %.2f points", symbol, spread_points)
                continue
            if not self._cooldown_passed(symbol):
                continue
            if len(positions) >= self.settings.max_open_positions:
                continue
            await self._open_trade(signal, spread_points)
            positions = await asyncio.to_thread(self.client.positions, self.settings.magic_number)

    async def _manage_positions(self, positions: list[Position]) -> None:
        for position in positions:
            tick = await asyncio.to_thread(self.client.tick, position.symbol)
            if tick is None:
                continue
            point = await asyncio.to_thread(self.client.point, position.symbol)
            decision = self.strategy.exit_decision(
                side=position.side,
                entry_price=position.price_open,
                current_bid=tick.bid,
                current_ask=tick.ask,
                point=point,
            )
            if decision.should_close:
                await self._close_position(position, decision)

    def _cooldown_passed(self, symbol: str) -> bool:
        last = self._last_trade_at.get(symbol, 0.0)
        return (time.monotonic() - last) * 1000 >= self.settings.cooldown_ms

    async def _open_trade(self, signal: Signal, spread_points: float) -> None:
        async with self._trade_lock:
            if self.settings.dry_run:
                self._last_trade_at[signal.symbol] = time.monotonic()
                await self._notify(
                    f"[DRY RUN] فتح {signal.side.value} {signal.symbol}\n"
                    f"السعر: {signal.price}\nالسبب: {signal.reason}\n"
                    f"السبريد: {spread_points:.2f} نقطة"
                )
                logger.info("DRY RUN open: %s", signal)
                return

            result = await asyncio.to_thread(
                self.client.open_market_order,
                signal.symbol,
                signal.side,
                self.settings.lot_size,
                self.settings.deviation,
                self.settings.magic_number,
            )
            if result.success:
                self._last_trade_at[signal.symbol] = time.monotonic()
                await self._notify(
                    f"فتح صفقة {signal.side.value} {signal.symbol}\n"
                    f"السعر: {result.price}\nالتذكرة: {result.ticket}\n"
                    f"السبب: {signal.reason}\nالوقت: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"
                )
                logger.info("Opened %s %s ticket=%s", signal.side, signal.symbol, result.ticket)
            else:
                logger.error("Open order rejected for %s: %s", signal.symbol, result.message)
                await self._notify(f"فشل فتح صفقة {signal.symbol}: {result.message}")

    async def _close_position(self, position: Position, decision: ExitDecision) -> None:
        async with self._trade_lock:
            if self.settings.dry_run:
                await self._notify(
                    f"[DRY RUN] إغلاق {position.side.value} {position.symbol}\n"
                    f"التذكرة: {position.ticket}\nالسبب: {decision.reason}\n"
                    f"الربح الحالي: {position.profit}"
                )
                logger.info("DRY RUN close ticket=%s: %s", position.ticket, decision.reason)
                return

            result = await asyncio.to_thread(
                self.client.close_position,
                position,
                self.settings.deviation,
                self.settings.magic_number,
            )
            if result.success:
                await self._notify(
                    f"إغلاق صفقة {position.side.value} {position.symbol}\n"
                    f"التذكرة: {position.ticket}\nالربح/الخسارة: {result.profit}\n"
                    f"السبب: {decision.reason}\nالوقت: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"
                )
                logger.info("Closed ticket=%s: %s", position.ticket, decision.reason)
            else:
                logger.error("Close order rejected ticket=%s: %s", position.ticket, result.message)
                await self._notify(f"فشل إغلاق التذكرة {position.ticket}: {result.message}")

    async def status_text(self) -> str:
        positions = await asyncio.to_thread(self.client.positions, self.settings.magic_number)
        lines = [
            f"الحالة: {'متوقف مؤقتًا' if self.paused else 'نشط'}",
            f"وضع التداول الحقيقي: {'مفعّل' if not self.settings.dry_run else 'معاينة DRY RUN'}",
            f"السبريد الأقصى: {self.max_spread_points} نقطة",
            f"الصفقات المفتوحة: {len(positions)}/{self.settings.max_open_positions}",
        ]
        for p in positions:
            lines.append(f"{p.ticket} | {p.symbol} | {p.side.value} | حجم {p.volume} | PnL {p.profit}")
        return "\n".join(lines)

    async def pause(self) -> None:
        self.paused = True

    async def resume(self) -> None:
        self.paused = False

    async def set_spread(self, value: int) -> None:
        if value < 0:
            raise ValueError("spread must be non-negative")
        self.max_spread_points = value

    async def close_all(self) -> str:
        if self.settings.dry_run:
            return "DRY RUN: لم يتم إرسال أوامر إغلاق حقيقية."
        results = await asyncio.to_thread(self.client.close_all_positions, self.settings.magic_number)
        successful = sum(1 for result in results if result.success)
        return f"تمت معالجة {len(results)} صفقة؛ أُغلقت بنجاح {successful}."
