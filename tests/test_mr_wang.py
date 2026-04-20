import pandas as pd

from src.agents.mr_wang import _apply_ma10_exit_rule


def test_ma10_rule_triggers_exit_when_price_below_ma10():
    prices_df = pd.DataFrame({"close": [100] * 10 + [95]})
    signal, confidence, meta = _apply_ma10_exit_rule("bullish", 60.0, prices_df)
    assert signal == "bearish"
    assert confidence >= 70.0
    assert meta["ma10_exit_triggered"] is True


def test_ma10_rule_prevents_bearish_when_price_above_ma10():
    prices_df = pd.DataFrame({"close": [100] * 10 + [105]})
    signal, confidence, meta = _apply_ma10_exit_rule("bearish", 80.0, prices_df)
    assert signal == "neutral"
    assert confidence <= 55.0
    assert meta["ma10_exit_triggered"] is False

