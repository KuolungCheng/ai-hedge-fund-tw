from types import SimpleNamespace

from src.agents.mr_hindsight import _compute_recent_return, _select_hindsight_signal


def test_select_hindsight_signal_prefers_price_trend_up():
    signal, source = _select_hindsight_signal(
        bullish_signals=0,
        bearish_signals=2,
        recent_return=0.08,
    )
    assert signal == "bullish"
    assert source == "price_trend"


def test_select_hindsight_signal_prefers_price_trend_down():
    signal, source = _select_hindsight_signal(
        bullish_signals=3,
        bearish_signals=0,
        recent_return=-0.07,
    )
    assert signal == "bearish"
    assert source == "price_trend"


def test_select_hindsight_signal_uses_news_when_trend_weak():
    signal, source = _select_hindsight_signal(
        bullish_signals=3,
        bearish_signals=1,
        recent_return=0.005,
    )
    assert signal == "bullish"
    assert source == "news_consensus"


def test_compute_recent_return_uses_last_20_bars():
    prices = [SimpleNamespace(close=float(v)) for v in range(100, 130)]
    recent_return = _compute_recent_return(prices)
    # last-20 uses closes 110 -> 129
    assert round(recent_return, 4) == round((129 - 110) / 110, 4)

