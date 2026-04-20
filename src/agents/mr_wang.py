# 老王 - sentiment_analyst_agent
import datetime
from langchain_core.messages import HumanMessage
from src.graph.state import AgentState, show_agent_reasoning
from src.utils.progress import progress
import pandas as pd
import numpy as np
import json
from src.utils.api_key import get_api_key_from_state
from src.tools.api import get_insider_trades, get_company_news, get_prices, prices_to_df


def _apply_ma10_exit_rule(
    signal: str,
    confidence: float,
    prices_df: pd.DataFrame | None,
) -> tuple[str, float, dict]:
    if prices_df is None or prices_df.empty or "close" not in prices_df.columns:
        return signal, confidence, {"ma10_available": False}

    ma10 = prices_df["close"].rolling(window=10).mean()
    if ma10.empty or pd.isna(ma10.iloc[-1]):
        return signal, confidence, {"ma10_available": False}

    close = float(prices_df["close"].iloc[-1])
    ma10_last = float(ma10.iloc[-1])
    below_ma10 = close < ma10_last

    # 腦王風格：跌破 10 日線優先視為出場訊號。
    if below_ma10:
        return "bearish", max(float(confidence), 70.0), {
            "ma10_available": True,
            "close": round(close, 2),
            "ma10": round(ma10_last, 2),
            "ma10_exit_triggered": True,
            "adjustment": "跌破10日線，優先轉為出場訊號",
        }

    # 若未跌破 10 日線，避免直接看空，至少維持中立。
    if signal == "bearish":
        return "neutral", min(float(confidence), 55.0), {
            "ma10_available": True,
            "close": round(close, 2),
            "ma10": round(ma10_last, 2),
            "ma10_exit_triggered": False,
            "adjustment": "未跌破10日線，避免直接看空",
        }

    return signal, float(confidence), {
        "ma10_available": True,
        "close": round(close, 2),
        "ma10": round(ma10_last, 2),
        "ma10_exit_triggered": False,
    }


##### Sentiment Agent #####
def sentiment_analyst_agent(state: AgentState, agent_id: str = "sentiment_analyst_agent"):
    """Analyzes market sentiment and generates trading signals for multiple tickers."""
    data = state.get("data", {})
    end_date = data.get("end_date")
    tickers = data.get("tickers")
    api_key = get_api_key_from_state(state, "FINANCIAL_DATASETS_API_KEY")
    # Initialize sentiment analysis for each ticker
    sentiment_analysis = {}

    for ticker in tickers:
        progress.update_status(agent_id, ticker, "取得內線交易資料")

        # Get the insider trades
        insider_trades = get_insider_trades(
            ticker=ticker,
            end_date=end_date,
            limit=1000,
            api_key=api_key,
        )

        progress.update_status(agent_id, ticker, "分析交易型態")

        # Get the signals from the insider trades
        transaction_shares = pd.Series([t.transaction_shares for t in insider_trades]).dropna()
        insider_signals = np.where(transaction_shares < 0, "bearish", "bullish").tolist()

        progress.update_status(agent_id, ticker, "取得公司新聞")

        # Get the company news
        company_news = get_company_news(ticker, end_date, limit=100, api_key=api_key)
        start_date = data.get("start_date")
        if not start_date:
            start_date = (datetime.datetime.strptime(end_date, "%Y-%m-%d") - datetime.timedelta(days=45)).strftime("%Y-%m-%d")
        prices = get_prices(ticker=ticker, start_date=start_date, end_date=end_date, api_key=api_key)
        prices_df = prices_to_df(prices) if prices else pd.DataFrame()

        # Get the sentiment from the company news
        sentiment = pd.Series([n.sentiment for n in company_news]).dropna()
        news_signals = np.where(sentiment == "negative", "bearish", 
                              np.where(sentiment == "positive", "bullish", "neutral")).tolist()
        
        progress.update_status(agent_id, ticker, "彙整訊號")
        # Combine signals from both sources with weights
        insider_weight = 0.3
        news_weight = 0.7
        
        # Calculate weighted signal counts
        bullish_signals = (
            insider_signals.count("bullish") * insider_weight +
            news_signals.count("bullish") * news_weight
        )
        bearish_signals = (
            insider_signals.count("bearish") * insider_weight +
            news_signals.count("bearish") * news_weight
        )

        if bullish_signals > bearish_signals:
            overall_signal = "bullish"
        elif bearish_signals > bullish_signals:
            overall_signal = "bearish"
        else:
            overall_signal = "neutral"

        # Calculate confidence level based on the weighted proportion
        total_weighted_signals = len(insider_signals) * insider_weight + len(news_signals) * news_weight
        confidence = 0  # Default confidence when there are no signals
        if total_weighted_signals > 0:
            confidence = round((max(bullish_signals, bearish_signals) / total_weighted_signals) * 100, 2)

        overall_signal, confidence, ma10_rule = _apply_ma10_exit_rule(
            signal=overall_signal,
            confidence=confidence,
            prices_df=prices_df,
        )
        
        # Create structured reasoning similar to technical analysis
        reasoning = {
            "insider_trading": {
                "signal": "bullish" if insider_signals.count("bullish") > insider_signals.count("bearish") else 
                         "bearish" if insider_signals.count("bearish") > insider_signals.count("bullish") else "neutral",
                "confidence": round((max(insider_signals.count("bullish"), insider_signals.count("bearish")) / max(len(insider_signals), 1)) * 100),
                "metrics": {
                    "total_trades": len(insider_signals),
                    "bullish_trades": insider_signals.count("bullish"),
                    "bearish_trades": insider_signals.count("bearish"),
                    "weight": insider_weight,
                    "weighted_bullish": round(insider_signals.count("bullish") * insider_weight, 1),
                    "weighted_bearish": round(insider_signals.count("bearish") * insider_weight, 1),
                }
            },
            "news_sentiment": {
                "signal": "bullish" if news_signals.count("bullish") > news_signals.count("bearish") else 
                         "bearish" if news_signals.count("bearish") > news_signals.count("bullish") else "neutral",
                "confidence": round((max(news_signals.count("bullish"), news_signals.count("bearish")) / max(len(news_signals), 1)) * 100),
                "metrics": {
                    "total_articles": len(news_signals),
                    "bullish_articles": news_signals.count("bullish"),
                    "bearish_articles": news_signals.count("bearish"),
                    "neutral_articles": news_signals.count("neutral"),
                    "weight": news_weight,
                    "weighted_bullish": round(news_signals.count("bullish") * news_weight, 1),
                    "weighted_bearish": round(news_signals.count("bearish") * news_weight, 1),
                }
            },
            "combined_analysis": {
                "total_weighted_bullish": round(bullish_signals, 1),
                "total_weighted_bearish": round(bearish_signals, 1),
                    "signal_determination": f"依加權訊號比較判定為 {'看多' if bullish_signals > bearish_signals else '看空' if bearish_signals > bullish_signals else '中立'}",
                    "ma10_exit_rule": ma10_rule,
            }
        }

        sentiment_analysis[ticker] = {
            "signal": overall_signal,
            "confidence": confidence,
            "reasoning": reasoning,
        }

        progress.update_status(agent_id, ticker, "完成", analysis=json.dumps(reasoning, indent=4))

    # Create the sentiment message
    message = HumanMessage(
        content=json.dumps(sentiment_analysis),
        name=agent_id,
    )

    # Print the reasoning if the flag is set
    if state["metadata"]["show_reasoning"]:
        show_agent_reasoning(sentiment_analysis, "情緒分析代理")

    # Add the signal to the analyst_signals list
    state["data"]["analyst_signals"][agent_id] = sentiment_analysis

    progress.update_status(agent_id, None, "完成")

    return {
        "messages": [message],
        "data": data,
    }
