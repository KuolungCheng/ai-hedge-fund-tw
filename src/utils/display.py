from colorama import Fore, Style
from tabulate import tabulate
from .analysts import ANALYST_CONFIG, ANALYST_ORDER
import os
import json
from typing import Any

ANALYST_KEY_TO_AGENT_IDS = {
    "airforce": ["airforce_agent", "valuation_analyst_agent"],
    "discount": ["discount_agent", "growth_analyst_agent"],
    "huang": ["huang_agent", "fundamentals_analyst_agent"],
    "cancer": ["cancer_agent", "technical_analyst_agent"],
    "wang": ["wang_agent", "sentiment_analyst_agent"],
    "hindsight": ["hindsight_agent", "news_sentiment_agent"],
}

AGENT_ID_TO_ANALYST_KEY = {
    agent_id: analyst_key
    for analyst_key, agent_ids in ANALYST_KEY_TO_AGENT_IDS.items()
    for agent_id in agent_ids
}

BEARISH_SCORE_MAX = 40
NEUTRAL_SCORE_MAX = 70


def get_action_color(action: str) -> str:
    return {
        "BUY": Fore.GREEN,
        "SELL": Fore.RED,
        "HOLD": Fore.YELLOW,
        "COVER": Fore.GREEN,
        "SHORT": Fore.RED,
    }.get(action.upper(), Fore.WHITE)


def get_action_label(action: str) -> str:
    return {
        "BUY": "買進",
        "SELL": "賣出",
        "HOLD": "持有",
        "COVER": "回補",
        "SHORT": "放空",
    }.get(action.upper(), action.upper())


def get_signal_label(signal: str) -> str:
    return {
        "BULLISH": "看多",
        "BEARISH": "看空",
        "NEUTRAL": "中立",
    }.get(signal.upper(), signal.upper())


def get_signal_color(signal: str) -> str:
    return {
        "BULLISH": Fore.GREEN,
        "BEARISH": Fore.RED,
        "NEUTRAL": Fore.YELLOW,
    }.get(signal.upper(), Fore.WHITE)


def _normalize_confidence(confidence: Any) -> float:
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, value))


def get_score_label(score: float) -> str:
    if score <= BEARISH_SCORE_MAX:
        return "看空"
    if score <= NEUTRAL_SCORE_MAX:
        return "中立"
    return "看多"


def get_score_color(score: float) -> str:
    if score <= BEARISH_SCORE_MAX:
        return Fore.RED
    if score <= NEUTRAL_SCORE_MAX:
        return Fore.YELLOW
    return Fore.GREEN


def get_analyst_score(signal: str, confidence: Any) -> int:
    normalized_signal = str(signal or "").upper()
    normalized_conf = _normalize_confidence(confidence)

    if normalized_signal == "BULLISH":
        # 看多越有把握，分數越接近 100
        score = 50.0 + (normalized_conf / 2.0)
    elif normalized_signal == "BEARISH":
        # 看空越有把握，分數越接近 0
        score = 50.0 - (normalized_conf / 2.0)
    else:
        # 中立預設落在中間區間
        score = 55.0

    return int(round(max(0.0, min(100.0, score))))


def get_analyst_display_name(agent_id: str) -> str:
    if agent_id == "risk_management_agent":
        return "風險管理"

    analyst_key = AGENT_ID_TO_ANALYST_KEY.get(agent_id, agent_id.replace("_agent", ""))
    return ANALYST_CONFIG.get(analyst_key, {}).get(
        "display_name",
        analyst_key.replace("_", " ").title(),
    )


def get_analyst_signal_for_ticker(analyst_signals: dict, ticker: str, analyst_key: str) -> dict | None:
    for agent_id in ANALYST_KEY_TO_AGENT_IDS.get(analyst_key, [f"{analyst_key}_agent"]):
        if ticker in analyst_signals.get(agent_id, {}):
            return analyst_signals[agent_id][ticker]
    return None


def localize_reasoning_text(text: str) -> str:
    if not text:
        return text

    replacements = {
        "All fundamentals and valuation signals bearish at max confidence.": "基本面與估值訊號皆為強烈看空（最高信心）。",
        "All fundamentals and valuation signals bullish at max confidence.": "基本面與估值訊號皆為強烈看多（最高信心）。",
        "bearish": "看空",
        "bullish": "看多",
        "neutral": "中立",
        "fundamentals": "基本面",
        "valuation": "估值",
        "signals": "訊號",
        "max confidence": "最高信心",
        "confidence": "信心",
    }

    localized = text
    for source, target in replacements.items():
        localized = localized.replace(source, target)
        localized = localized.replace(source.capitalize(), target)
    return localized


def sort_agent_signals(signals):
    """依固定順序排序代理訊號。"""
    # Create order mapping from ANALYST_ORDER
    analyst_order = {display: idx for idx, (display, _) in enumerate(ANALYST_ORDER)}
    analyst_order["風險管理"] = len(ANALYST_ORDER)  # 風險管理固定放最後
    analyst_order["Risk Management"] = len(ANALYST_ORDER)  # 相容舊文字

    return sorted(signals, key=lambda x: analyst_order.get(x[0], 999))


def print_trading_output(result: dict) -> None:
    """
    以彩色表格印出多檔股票的交易結果。

    Args:
        result (dict): 含多檔股票決策與分析訊號的資料
    """
    decisions = result.get("decisions")
    if not decisions:
        print(f"{Fore.RED}目前沒有可用的交易決策{Style.RESET_ALL}")
        return

    # Print decisions for each ticker
    for ticker, decision in decisions.items():
        print(f"\n{Fore.WHITE}{Style.BRIGHT}{Fore.CYAN}{ticker}{Style.RESET_ALL}{Fore.WHITE}{Style.BRIGHT} 分析結果{Style.RESET_ALL}")
        print(f"{Fore.WHITE}{Style.BRIGHT}{'=' * 50}{Style.RESET_ALL}")

        # Prepare analyst signals table for this ticker
        table_data = []
        for agent, signals in result.get("analyst_signals", {}).items():
            if ticker not in signals:
                continue
                
            # Skip Risk Management agent in the signals section
            if agent == "risk_management_agent":
                continue

            signal = signals[ticker]
            agent_name = get_analyst_display_name(agent)
            signal_type = signal.get("signal", "").upper()
            confidence = signal.get("confidence", 0)

            signal_color = get_signal_color(signal_type)
            signal_label = get_signal_label(signal_type)
            
            # Get reasoning if available
            reasoning_str = ""
            if "reasoning" in signal and signal["reasoning"]:
                reasoning = signal["reasoning"]
                
                # Handle different types of reasoning (string, dict, etc.)
                if isinstance(reasoning, str):
                    reasoning_str = localize_reasoning_text(reasoning)
                elif isinstance(reasoning, dict):
                    # Convert dict to string representation
                    reasoning_str = json.dumps(reasoning, indent=2)
                else:
                    # Convert any other type to string
                    reasoning_str = str(reasoning)
                
                # Wrap long reasoning text to make it more readable
                wrapped_reasoning = ""
                current_line = ""
                # Use a fixed width of 60 characters to match the table column width
                max_line_length = 60
                for word in reasoning_str.split():
                    if len(current_line) + len(word) + 1 > max_line_length:
                        wrapped_reasoning += current_line + "\n"
                        current_line = word
                    else:
                        if current_line:
                            current_line += " " + word
                        else:
                            current_line = word
                if current_line:
                    wrapped_reasoning += current_line
                
                reasoning_str = wrapped_reasoning

            table_data.append(
                [
                    f"{Fore.CYAN}{agent_name}{Style.RESET_ALL}",
                    f"{signal_color}{signal_label}{Style.RESET_ALL}",
                    f"{Fore.WHITE}{confidence}%{Style.RESET_ALL}",
                    f"{Fore.WHITE}{reasoning_str}{Style.RESET_ALL}",
                ]
            )

        # Sort the signals according to the predefined order
        table_data = sort_agent_signals(table_data)

        print(f"\n{Fore.WHITE}{Style.BRIGHT}代理分析：{Style.RESET_ALL}[{Fore.CYAN}{ticker}{Style.RESET_ALL}]")
        print(
            tabulate(
                table_data,
                headers=[f"{Fore.WHITE}代理", "訊號", "信心分數", "推理依據"],
                tablefmt="grid",
                colalign=("left", "center", "right", "left"),
            )
        )

    # Print Portfolio Summary
    print(f"\n{Fore.WHITE}{Style.BRIGHT}投資組合總覽：{Style.RESET_ALL}")
    portfolio_data = []
    
    strategy_data = []

    analyst_signals = result.get("analyst_signals", {})
    for ticker, decision in decisions.items():
        action = decision.get("action", "").upper()
        action_color = get_action_color(action)
        action_label = get_action_label(action)

        # Calculate analyst signal counts
        bullish_count = 0
        bearish_count = 0
        neutral_count = 0
        if analyst_signals:
            for agent, signals in analyst_signals.items():
                if ticker in signals:
                    signal = signals[ticker].get("signal", "").upper()
                    if signal == "BULLISH":
                        bullish_count += 1
                    elif signal == "BEARISH":
                        bearish_count += 1
                    elif signal == "NEUTRAL":
                        neutral_count += 1

        portfolio_data.append(
            [
                f"{Fore.CYAN}{ticker}{Style.RESET_ALL}",
                f"{action_color}{action_label}{Style.RESET_ALL}",
                f"{Fore.WHITE}{decision.get('confidence'):.1f}%{Style.RESET_ALL}",
                f"{Fore.GREEN}{bullish_count}{Style.RESET_ALL}",
                f"{Fore.RED}{bearish_count}{Style.RESET_ALL}",
                f"{Fore.YELLOW}{neutral_count}{Style.RESET_ALL}",
            ]
        )

        reasoning = decision.get("reasoning")
        if reasoning:
            if isinstance(reasoning, str):
                reasoning_text = localize_reasoning_text(reasoning)
            elif isinstance(reasoning, dict):
                reasoning_text = json.dumps(reasoning, ensure_ascii=False)
            else:
                reasoning_text = str(reasoning)
            strategy_data.append(
                [
                    f"{Fore.CYAN}{ticker}{Style.RESET_ALL}",
                    f"{Fore.WHITE}{reasoning_text}{Style.RESET_ALL}",
                ]
            )

    headers = [
        f"{Fore.WHITE}股票代碼",
        f"{Fore.WHITE}動作",
        f"{Fore.WHITE}信心分數",
        f"{Fore.WHITE}看多",
        f"{Fore.WHITE}看空",
        f"{Fore.WHITE}中立",
    ]
    
    # Print the portfolio summary table
    print(
        tabulate(
            portfolio_data,
            headers=headers,
            tablefmt="grid",
            colalign=("left", "center", "right", "center", "center", "center"),
        )
    )

    # Print per-analyst 0-100 score in portfolio summary
    analyst_score_rows = []
    analyst_score_headers = [f"{Fore.WHITE}股票代碼"] + [f"{Fore.WHITE}{display}" for display, _ in ANALYST_ORDER]
    for ticker in decisions.keys():
        row = [f"{Fore.CYAN}{ticker}{Style.RESET_ALL}"]
        for _, analyst_key in ANALYST_ORDER:
            signal_payload = get_analyst_signal_for_ticker(analyst_signals, ticker, analyst_key)
            if not signal_payload:
                row.append("-")
                continue
            signal_raw = str(signal_payload.get("signal", "")).upper()
            confidence = signal_payload.get("confidence")
            score = get_analyst_score(signal_raw, confidence)
            score_label = get_score_label(score)
            score_color = get_score_color(score)
            row.append(f"{score_color}{score_label} {score}{Style.RESET_ALL}")
        analyst_score_rows.append(row)

    if analyst_score_rows:
        print(f"\n{Fore.WHITE}{Style.BRIGHT}分析師個別評分：{Style.RESET_ALL}")
        print(
            tabulate(
                analyst_score_rows,
                headers=analyst_score_headers,
                tablefmt="grid",
                colalign=("left", "center", "center", "center", "center", "center", "center"),
            )
        )
     
    # Print per-ticker portfolio strategy to avoid dropping multi-ticker reasoning
    if strategy_data:
        print(f"\n{Fore.WHITE}{Style.BRIGHT}投資組合策略：{Style.RESET_ALL}")
        print(
            tabulate(
                strategy_data,
                headers=[f"{Fore.WHITE}股票代碼", f"{Fore.WHITE}策略說明"],
                tablefmt="grid",
                colalign=("left", "left"),
            )
        )


def print_backtest_results(table_rows: list) -> None:
    """以易讀表格印出回測結果"""
    # Clear the screen
    os.system("cls" if os.name == "nt" else "clear")

    # Split rows into ticker rows and summary rows
    ticker_rows = []
    summary_rows = []

    for row in table_rows:
        if isinstance(row[1], str) and ("PORTFOLIO SUMMARY" in row[1] or "投資組合總覽" in row[1]):
            summary_rows.append(row)
        else:
            ticker_rows.append(row)

    # Display latest portfolio summary
    if summary_rows:
        # Pick the most recent summary by date (YYYY-MM-DD)
        latest_summary = max(summary_rows, key=lambda r: r[0])
        print(f"\n{Fore.WHITE}{Style.BRIGHT}投資組合總覽：{Style.RESET_ALL}")

        # Adjusted indexes after adding Long/Short Shares
        position_str = latest_summary[7].split("$")[1].split(Style.RESET_ALL)[0].replace(",", "")
        cash_str     = latest_summary[8].split("$")[1].split(Style.RESET_ALL)[0].replace(",", "")
        total_str    = latest_summary[9].split("$")[1].split(Style.RESET_ALL)[0].replace(",", "")

        print(f"現金餘額：{Fore.CYAN}${float(cash_str):,.2f}{Style.RESET_ALL}")
        print(f"持倉總市值：{Fore.YELLOW}${float(position_str):,.2f}{Style.RESET_ALL}")
        print(f"資產總值：{Fore.WHITE}${float(total_str):,.2f}{Style.RESET_ALL}")
        print(f"組合報酬率：{latest_summary[10]}")
        if len(latest_summary) > 14 and latest_summary[14]:
            print(f"基準報酬率：{latest_summary[14]}")

        # Display performance metrics if available
        if latest_summary[11]:  # Sharpe ratio
            print(f"夏普值：{latest_summary[11]}")
        if latest_summary[12]:  # Sortino ratio
            print(f"索提諾值：{latest_summary[12]}")
        if latest_summary[13]:  # Max drawdown
            print(f"最大回撤：{latest_summary[13]}")

    # Add vertical spacing
    print("\n" * 2)

    # Print the table with just ticker rows
    print(
        tabulate(
            ticker_rows,
            headers=[
                "日期",
                "股票代碼",
                "動作",
                "數量",
                "價格",
                "多頭股數",
                "空頭股數",
                "持倉市值",
            ],
            tablefmt="grid",
            colalign=(
                "left",    # Date
                "left",    # Ticker
                "center",  # Action
                "right",   # Quantity
                "right",   # Price
                "right",   # Long Shares
                "right",   # Short Shares
                "right",   # Position Value
            ),
        )
    )

    # Add vertical spacing
    print("\n" * 4)


def format_backtest_row(
    date: str,
    ticker: str,
    action: str,
    quantity: float,
    price: float,
    long_shares: float = 0,
    short_shares: float = 0,
    position_value: float = 0,
    is_summary: bool = False,
    total_value: float = None,
    return_pct: float = None,
    cash_balance: float = None,
    total_position_value: float = None,
    sharpe_ratio: float = None,
    sortino_ratio: float = None,
    max_drawdown: float = None,
    benchmark_return_pct: float | None = None,
) -> list[any]:
    """格式化單筆回測資料列"""
    # Color the action
    action_color = get_action_color(action)
    action_label = get_action_label(action)

    if is_summary:
        return_color = Fore.GREEN if return_pct >= 0 else Fore.RED
        benchmark_str = ""
        if benchmark_return_pct is not None:
            bench_color = Fore.GREEN if benchmark_return_pct >= 0 else Fore.RED
            benchmark_str = f"{bench_color}{benchmark_return_pct:+.2f}%{Style.RESET_ALL}"
        return [
            date,
            f"{Fore.WHITE}{Style.BRIGHT}投資組合總覽{Style.RESET_ALL}",
            "",  # Action
            "",  # Quantity
            "",  # Price
            "",  # Long Shares
            "",  # Short Shares
            f"{Fore.YELLOW}${total_position_value:,.2f}{Style.RESET_ALL}",  # Total Position Value
            f"{Fore.CYAN}${cash_balance:,.2f}{Style.RESET_ALL}",  # Cash Balance
            f"{Fore.WHITE}${total_value:,.2f}{Style.RESET_ALL}",  # Total Value
            f"{return_color}{return_pct:+.2f}%{Style.RESET_ALL}",  # Return
            f"{Fore.YELLOW}{sharpe_ratio:.2f}{Style.RESET_ALL}" if sharpe_ratio is not None else "",  # Sharpe Ratio
            f"{Fore.YELLOW}{sortino_ratio:.2f}{Style.RESET_ALL}" if sortino_ratio is not None else "",  # Sortino Ratio
            f"{Fore.RED}{max_drawdown:.2f}%{Style.RESET_ALL}" if max_drawdown is not None else "",  # Max Drawdown (signed)
            benchmark_str,  # Benchmark (S&P 500)
        ]
    else:
        return [
            date,
            f"{Fore.CYAN}{ticker}{Style.RESET_ALL}",
            f"{action_color}{action_label}{Style.RESET_ALL}",
            f"{action_color}{quantity:,.0f}{Style.RESET_ALL}",
            f"{Fore.WHITE}{price:,.2f}{Style.RESET_ALL}",
            f"{Fore.GREEN}{long_shares:,.0f}{Style.RESET_ALL}",   # Long Shares
            f"{Fore.RED}{short_shares:,.0f}{Style.RESET_ALL}",    # Short Shares
            f"{Fore.YELLOW}{position_value:,.2f}{Style.RESET_ALL}",
        ]
