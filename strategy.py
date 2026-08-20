from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True, slots=True)
class Tick:
    symbol: str
    bid: float
    ask: float
    time_msc: int


@dataclass(frozen=True, slots=True)
class Signal:
    symbol: str
    side: Side
    price: float
    reason: str


@dataclass(frozen=True, slots=True)
class ExitDecision:
    should_close: bool
    reason: str = ""


class TickScalpingStrategy:
    """Conservative tick-jump signal generator and point-based exit logic."""

    def __init__(self, trigger_points: int, take_profit_points: int, stop_loss_points: int):
        self.trigger_points = trigger_points
        self.take_profit_points = take_profit_points
        self.stop_loss_points = stop_loss_points
        self._previous: dict[str, Tick] = {}

    def evaluate_signal(self, tick: Tick, point: float) -> Optional[Signal]:
        previous = self._previous.get(tick.symbol)
        self._previous[tick.symbol] = tick
        if previous is None or point <= 0:
            return None

        threshold = self.trigger_points * point
        epsilon = point * 1e-9
        bid_jump = tick.bid - previous.bid
        ask_drop = previous.ask - tick.ask

        if bid_jump >= threshold - epsilon:
            return Signal(tick.symbol, Side.BUY, tick.ask, f"bid_jump={bid_jump / point:.2f} points")
        if ask_drop >= threshold - epsilon:
            return Signal(tick.symbol, Side.SELL, tick.bid, f"ask_drop={ask_drop / point:.2f} points")
        return None

    def exit_decision(self, side: Side, entry_price: float, current_bid: float, current_ask: float, point: float) -> ExitDecision:
        if point <= 0:
            return ExitDecision(False)

        epsilon_points = 1e-9
        if side == Side.BUY:
            profit_points = (current_bid - entry_price) / point
            if profit_points >= self.take_profit_points - epsilon_points:
                return ExitDecision(True, f"take_profit={profit_points:.2f} points")
            if profit_points <= -self.stop_loss_points + epsilon_points:
                return ExitDecision(True, f"stop_loss={profit_points:.2f} points")
        else:
            profit_points = (entry_price - current_ask) / point
            if profit_points >= self.take_profit_points - epsilon_points:
                return ExitDecision(True, f"take_profit={profit_points:.2f} points")
            if profit_points <= -self.stop_loss_points + epsilon_points:
                return ExitDecision(True, f"stop_loss={profit_points:.2f} points")

        return ExitDecision(False)
