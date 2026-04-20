from src.agents.mr_huang import _build_price_ratio_signal, _get_valuation_thresholds


def test_taiwan_ticker_uses_relaxed_valuation_thresholds():
    thresholds = _get_valuation_thresholds("2330.TW")
    assert thresholds == {"pe": 35.0, "pb": 6.0, "ps": 8.0}


def test_us_ticker_keeps_original_valuation_thresholds():
    thresholds = _get_valuation_thresholds("AAPL")
    assert thresholds == {"pe": 25.0, "pb": 3.0, "ps": 5.0}


def test_taiwan_valuation_signal_not_forced_bearish_by_old_us_thresholds():
    signal, reasoning = _build_price_ratio_signal(
        ticker="2330.TW",
        pe_ratio=30.0,
        pb_ratio=5.0,
        ps_ratio=7.0,
    )
    assert signal == "bullish"
    assert "估值門檻(PE/PB/PS): 35/6/8" in reasoning["details"]


def test_two_high_valuations_still_bearish():
    signal, _ = _build_price_ratio_signal(
        ticker="2330.TW",
        pe_ratio=40.0,
        pb_ratio=7.0,
        ps_ratio=6.0,
    )
    assert signal == "bearish"

