import pandas as pd

from src.agents.mr_cancer import apply_trend_bias


def test_trend_bias_lifts_neutral_to_bullish_when_uptrend_above_ma10():
    prices_df = pd.DataFrame({"close": [100] * 10 + [106]})
    combined, meta = apply_trend_bias(
        combined_signal={"signal": "neutral", "confidence": 0.3},
        trend_signal={"signal": "bullish"},
        momentum_signal={"signal": "neutral"},
        prices_df=prices_df,
    )
    assert combined["signal"] == "bullish"
    assert combined["confidence"] >= 0.55
    assert meta["applied"] is True


def test_trend_bias_lifts_neutral_to_bearish_when_downtrend_below_ma10():
    prices_df = pd.DataFrame({"close": [100] * 10 + [94]})
    combined, meta = apply_trend_bias(
        combined_signal={"signal": "neutral", "confidence": 0.3},
        trend_signal={"signal": "bearish"},
        momentum_signal={"signal": "neutral"},
        prices_df=prices_df,
    )
    assert combined["signal"] == "bearish"
    assert combined["confidence"] >= 0.55
    assert meta["applied"] is True

