# 照哥 - fundamentals_analyst_agent
from langchain_core.messages import HumanMessage
from src.graph.state import AgentState, show_agent_reasoning
from src.utils.api_key import get_api_key_from_state
from src.utils.progress import progress
import json

from src.tools.api import get_financial_metrics


def _is_taiwan_ticker(ticker: str) -> bool:
    normalized = (ticker or "").upper()
    return normalized.endswith(".TW") or normalized.endswith(".TWO")


def _get_valuation_thresholds(ticker: str) -> dict[str, float]:
    # 台股估值區間通常高於美股常見門檻，使用較寬鬆閾值避免系統性誤判偏空。
    if _is_taiwan_ticker(ticker):
        return {"pe": 35.0, "pb": 6.0, "ps": 8.0}
    return {"pe": 25.0, "pb": 3.0, "ps": 5.0}


def _build_price_ratio_signal(
        ticker: str,
        pe_ratio: float | None,
        pb_ratio: float | None,
        ps_ratio: float | None,
) -> tuple[str, dict]:
    thresholds = _get_valuation_thresholds(ticker)
    ratios = [
        ("pe", pe_ratio, thresholds["pe"]),
        ("pb", pb_ratio, thresholds["pb"]),
        ("ps", ps_ratio, thresholds["ps"]),
    ]
    available = [(name, value, threshold) for name, value, threshold in ratios if value is not None]
    above_threshold = sum(value > threshold for _, value, threshold in available)

    if not available:
        signal = "neutral"
    elif above_threshold >= 2:
        signal = "bearish"
    elif above_threshold == 0 and len(available) >= 2:
        signal = "bullish"
    else:
        signal = "neutral"

    details = (
        (f"P/E: {pe_ratio:.2f}" if pe_ratio is not None else "P/E: N/A")
        + ", "
        + (f"P/B: {pb_ratio:.2f}" if pb_ratio is not None else "P/B: N/A")
        + ", "
        + (f"P/S: {ps_ratio:.2f}" if ps_ratio is not None else "P/S: N/A")
        + ", "
        + f"估值門檻(PE/PB/PS): {thresholds['pe']:.0f}/{thresholds['pb']:.0f}/{thresholds['ps']:.0f}"
    )
    return signal, {"signal": signal, "details": details}


##### Fundamental Agent #####
def fundamentals_analyst_agent(state: AgentState, agent_id: str = "fundamentals_analyst_agent"):
    """Analyzes fundamental data and generates trading signals for multiple tickers."""
    data = state["data"]
    end_date = data["end_date"]
    tickers = data["tickers"]
    api_key = get_api_key_from_state(state, "FINANCIAL_DATASETS_API_KEY")
    # Initialize fundamental analysis for each ticker
    fundamental_analysis = {}

    for ticker in tickers:
        progress.update_status(agent_id, ticker, "取得財務指標")

        # Get the financial metrics
        financial_metrics = get_financial_metrics(
            ticker=ticker,
            end_date=end_date,
            period="ttm",
            limit=10,
            api_key=api_key,
        )

        if not financial_metrics:
            progress.update_status(agent_id, ticker, "失敗：找不到財務指標")
            continue

        # Pull the most recent financial metrics
        metrics = financial_metrics[0]

        # Initialize signals list for different fundamental aspects
        signals = []
        reasoning = {}

        progress.update_status(agent_id, ticker, "分析獲利能力")
        # 1. Profitability Analysis
        return_on_equity = metrics.return_on_equity
        net_margin = metrics.net_margin
        operating_margin = metrics.operating_margin

        thresholds = [
            (return_on_equity, 0.15),  # Strong ROE above 15%
            (net_margin, 0.20),  # Healthy profit margins
            (operating_margin, 0.15),  # Strong operating efficiency
        ]
        profitability_score = sum(metric is not None and metric > threshold for metric, threshold in thresholds)

        signals.append("bullish" if profitability_score >= 2 else "bearish" if profitability_score == 0 else "neutral")
        reasoning["profitability_signal"] = {
            "signal": signals[0],
            "details": (f"ROE: {return_on_equity:.2%}" if return_on_equity else "ROE: N/A") + ", " + (f"Net Margin: {net_margin:.2%}" if net_margin else "Net Margin: N/A") + ", " + (f"Op Margin: {operating_margin:.2%}" if operating_margin else "Op Margin: N/A"),
        }

        progress.update_status(agent_id, ticker, "分析成長性")
        # 2. Growth Analysis
        revenue_growth = metrics.revenue_growth
        earnings_growth = metrics.earnings_growth
        book_value_growth = metrics.book_value_growth

        thresholds = [
            (revenue_growth, 0.10),  # 10% revenue growth
            (earnings_growth, 0.10),  # 10% earnings growth
            (book_value_growth, 0.10),  # 10% book value growth
        ]
        growth_score = sum(metric is not None and metric > threshold for metric, threshold in thresholds)

        signals.append("bullish" if growth_score >= 2 else "bearish" if growth_score == 0 else "neutral")
        reasoning["growth_signal"] = {
            "signal": signals[1],
            "details": (f"Revenue Growth: {revenue_growth:.2%}" if revenue_growth else "Revenue Growth: N/A") + ", " + (f"Earnings Growth: {earnings_growth:.2%}" if earnings_growth else "Earnings Growth: N/A"),
        }

        progress.update_status(agent_id, ticker, "分析財務體質")
        # 3. Financial Health
        current_ratio = metrics.current_ratio
        debt_to_equity = metrics.debt_to_equity
        free_cash_flow_per_share = metrics.free_cash_flow_per_share
        earnings_per_share = metrics.earnings_per_share

        health_score = 0
        if current_ratio and current_ratio > 1.5:  # Strong liquidity
            health_score += 1
        if debt_to_equity and debt_to_equity < 0.5:  # Conservative debt levels
            health_score += 1
        if free_cash_flow_per_share and earnings_per_share and free_cash_flow_per_share > earnings_per_share * 0.8:  # Strong FCF conversion
            health_score += 1

        signals.append("bullish" if health_score >= 2 else "bearish" if health_score == 0 else "neutral")
        reasoning["financial_health_signal"] = {
            "signal": signals[2],
            "details": (f"Current Ratio: {current_ratio:.2f}" if current_ratio else "Current Ratio: N/A") + ", " + (f"D/E: {debt_to_equity:.2f}" if debt_to_equity else "D/E: N/A"),
        }

        progress.update_status(agent_id, ticker, "分析估值比率")
        # 4. Price to X ratios
        pe_ratio = metrics.price_to_earnings_ratio
        pb_ratio = metrics.price_to_book_ratio
        ps_ratio = metrics.price_to_sales_ratio

        valuation_signal, valuation_reasoning = _build_price_ratio_signal(
            ticker=ticker,
            pe_ratio=pe_ratio,
            pb_ratio=pb_ratio,
            ps_ratio=ps_ratio,
        )
        signals.append(valuation_signal)
        reasoning["price_ratios_signal"] = valuation_reasoning

        progress.update_status(agent_id, ticker, "計算最終訊號")
        # Determine overall signal
        bullish_signals = signals.count("bullish")
        bearish_signals = signals.count("bearish")

        if bullish_signals > bearish_signals:
            overall_signal = "bullish"
        elif bearish_signals > bullish_signals:
            overall_signal = "bearish"
        else:
            overall_signal = "neutral"

        # Calculate confidence level
        total_signals = len(signals)
        confidence = round(max(bullish_signals, bearish_signals) / total_signals, 2) * 100

        fundamental_analysis[ticker] = {
            "signal": overall_signal,
            "confidence": confidence,
            "reasoning": reasoning,
        }

        progress.update_status(agent_id, ticker, "完成", analysis=json.dumps(reasoning, indent=4))

    # Create the fundamental analysis message
    message = HumanMessage(
        content=json.dumps(fundamental_analysis),
        name=agent_id,
    )

    # Print the reasoning if the flag is set
    if state["metadata"]["show_reasoning"]:
        show_agent_reasoning(fundamental_analysis, "基本面分析代理")

    # Add the signal to the analyst_signals list
    state["data"]["analyst_signals"][agent_id] = fundamental_analysis

    progress.update_status(agent_id, None, "完成")
    
    return {
        "messages": [message],
        "data": data,
    }
