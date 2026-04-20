from src.agents.portfolio_manager import _build_reasoning, _compute_consensus_confidence


def test_consensus_confidence_penalizes_neutral_signals():
    signals = {
        "a1": {"sig": "BEARISH", "conf": 100},
        "a2": {"sig": "BEARISH", "conf": 100},
        "a3": {"sig": "BEARISH", "conf": 100},
        "a4": {"sig": "NEUTRAL", "conf": 100},
        "a5": {"sig": "NEUTRAL", "conf": 100},
        "a6": {"sig": "NEUTRAL", "conf": 100},
    }
    assert _compute_consensus_confidence("short", signals) == 50


def test_reasoning_uses_signal_counts_not_fundamental_claims():
    signals = {
        "a1": {"sig": "BEARISH", "conf": 80},
        "a2": {"sig": "BULLISH", "conf": 70},
        "a3": {"sig": "NEUTRAL", "conf": 60},
    }
    reasoning = _build_reasoning("short", signals)
    assert "看多1、看空1、中立1" in reasoning
    assert "平均分數" not in reasoning
    assert "基本面" not in reasoning
