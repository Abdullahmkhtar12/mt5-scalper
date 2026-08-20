from strategy import Side, Tick, TickScalpingStrategy


def test_buy_signal_when_bid_jumps_by_threshold() -> None:
    strategy = TickScalpingStrategy(trigger_points=2, take_profit_points=5, stop_loss_points=10)
    strategy.evaluate_signal(Tick("EURUSD", 1.10000, 1.10002, 1), 0.00001)
    signal = strategy.evaluate_signal(Tick("EURUSD", 1.10002, 1.10004, 2), 0.00001)
    assert signal is not None
    assert signal.side == Side.BUY


def test_sell_signal_when_ask_drops_by_threshold() -> None:
    strategy = TickScalpingStrategy(trigger_points=2, take_profit_points=5, stop_loss_points=10)
    strategy.evaluate_signal(Tick("EURUSD", 1.10000, 1.10002, 1), 0.00001)
    signal = strategy.evaluate_signal(Tick("EURUSD", 1.09998, 1.10000, 2), 0.00001)
    assert signal is not None
    assert signal.side == Side.SELL


def test_buy_take_profit_and_stop_loss() -> None:
    strategy = TickScalpingStrategy(trigger_points=1, take_profit_points=5, stop_loss_points=10)
    assert strategy.exit_decision(Side.BUY, 1.10000, 1.10005, 1.10007, 0.00001).should_close
    assert strategy.exit_decision(Side.BUY, 1.10000, 1.09990, 1.09992, 0.00001).should_close


def test_sell_take_profit_and_stop_loss() -> None:
    strategy = TickScalpingStrategy(trigger_points=1, take_profit_points=5, stop_loss_points=10)
    assert strategy.exit_decision(Side.SELL, 1.10000, 1.09993, 1.09995, 0.00001).should_close
    assert strategy.exit_decision(Side.SELL, 1.10000, 1.10010, 1.10012, 0.00001).should_close
