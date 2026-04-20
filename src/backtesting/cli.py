from __future__ import annotations

import sys
from datetime import datetime
from dateutil.relativedelta import relativedelta
import argparse

from colorama import Fore, Style, init
import questionary

from .engine import BacktestEngine
from src.llm.models import LLM_ORDER, OLLAMA_LLM_ORDER, get_model_info, ModelProvider
from src.utils.analysts import ANALYST_ORDER
from src.main import run_hedge_fund
from src.utils.ollama import ensure_ollama_and_model


def main() -> int:
    parser = argparse.ArgumentParser(description="執行回測引擎（模組化）")
    parser.add_argument("--tickers", type=str, required=False, help="以逗號分隔的股票代碼")
    parser.add_argument(
        "--end-date",
        type=str,
        default=datetime.now().strftime("%Y-%m-%d"),
        help="結束日期 YYYY-MM-DD",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=(datetime.now() - relativedelta(months=1)).strftime("%Y-%m-%d"),
        help="開始日期 YYYY-MM-DD",
    )
    parser.add_argument("--initial-capital", type=float, default=100000)
    parser.add_argument("--margin-requirement", type=float, default=0.0)
    parser.add_argument(
        "--base-position-limit",
        type=float,
        default=0.20,
        help="風險管理基準部位上限（0~1 小數，例如 0.2 代表 20%%），預設 0.2",
    )
    parser.add_argument(
        "--analysts",
        type=str,
        required=False,
        help="以逗號分隔要使用的分析代理清單（例如：wang,huang；輸入 all 代表全部）",
    )
    parser.add_argument("--analysts-all", action="store_true", help="使用全部可用分析代理（會覆蓋 --analysts）")
    parser.add_argument("--ollama", action="store_true")

    args = parser.parse_args()
    init(autoreset=True)

    if not (0 < args.base_position_limit <= 1):
        parser.error("--base-position-limit 必須介於 0（不含）到 1（含）之間")

    tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else []

    # Analysts selection is simplified; no interactive prompts here
    if args.analysts_all:
        selected_analysts = [a[1] for a in ANALYST_ORDER]
    elif args.analysts:
        parsed_analysts = [a.strip() for a in args.analysts.split(",") if a.strip()]
        if any(a.lower() == "all" for a in parsed_analysts):
            selected_analysts = [a[1] for a in ANALYST_ORDER]
        else:
            selected_analysts = parsed_analysts
    else:
        # Interactive analyst selection (same as legacy backtester)
        choices = questionary.checkbox(
            "請使用空白鍵勾選或取消分析代理。",
            choices=[questionary.Choice(display, value=value) for display, value in ANALYST_ORDER],
            instruction="\n\n按 'a' 可全選/全不選。\n\n完成後按 Enter 執行對沖基金流程。",
            validate=lambda x: len(x) > 0 or "至少要選擇一位分析代理。",
            style=questionary.Style(
                [
                    ("checkbox-selected", "fg:green"),
                    ("selected", "fg:green noinherit"),
                    ("highlighted", "noinherit"),
                    ("pointer", "noinherit"),
                ]
            ),
        ).ask()
        if not choices:
            print("\n\n已收到中斷訊號，正在結束。")
            return 1
        selected_analysts = choices
        print(
            f"\n已選擇分析代理："
            f"{', '.join(Fore.GREEN + choice.title().replace('_', ' ') + Style.RESET_ALL for choice in choices)}\n"
        )

    # Model selection simplified: default to first ordered model or Ollama flag
    if args.ollama:
        print(f"{Fore.CYAN}已啟用 Ollama 本地推論。{Style.RESET_ALL}")
        model_name = questionary.select(
            "請選擇 Ollama 模型：",
            choices=[questionary.Choice(display, value=value) for display, value, _ in OLLAMA_LLM_ORDER],
            style=questionary.Style(
                [
                    ("selected", "fg:green bold"),
                    ("pointer", "fg:green bold"),
                    ("highlighted", "fg:green"),
                    ("answer", "fg:green bold"),
                ]
            ),
        ).ask()
        if not model_name:
            print("\n\n已收到中斷訊號，正在結束。")
            return 1
        if model_name == "-":
            model_name = questionary.text("請輸入自訂模型名稱：").ask()
            if not model_name:
                print("\n\n已收到中斷訊號，正在結束。")
                return 1
        if not ensure_ollama_and_model(model_name):
            print(f"{Fore.RED}找不到可用的 Ollama 或所選模型，無法繼續。{Style.RESET_ALL}")
            return 1
        model_provider = ModelProvider.OLLAMA.value
        print(
            f"\n已選擇 {Fore.CYAN}Ollama{Style.RESET_ALL} 模型：{Fore.GREEN + Style.BRIGHT}{model_name}{Style.RESET_ALL}\n"
        )
    else:
        model_choice = questionary.select(
            "請選擇 LLM 模型：",
            choices=[questionary.Choice(display, value=(name, provider)) for display, name, provider in LLM_ORDER],
            style=questionary.Style(
                [
                    ("selected", "fg:green bold"),
                    ("pointer", "fg:green bold"),
                    ("highlighted", "fg:green"),
                    ("answer", "fg:green bold"),
                ]
            ),
        ).ask()
        if not model_choice:
            print("\n\n已收到中斷訊號，正在結束。")
            return 1
        model_name, model_provider = model_choice
        model_info = get_model_info(model_name, model_provider)
        if model_info and model_info.is_custom():
            model_name = questionary.text("請輸入自訂模型名稱：").ask()
            if not model_name:
                print("\n\n已收到中斷訊號，正在結束。")
                return 1
        print(
            f"\n已選擇 {Fore.CYAN}{model_provider}{Style.RESET_ALL} 模型：{Fore.GREEN + Style.BRIGHT}{model_name}{Style.RESET_ALL}\n"
        )

    engine = BacktestEngine(
        agent=run_hedge_fund,
        tickers=tickers,
        start_date=args.start_date,
        end_date=args.end_date,
        initial_capital=args.initial_capital,
        model_name=model_name,
        model_provider=model_provider,
        selected_analysts=selected_analysts,
        initial_margin_requirement=args.margin_requirement,
        base_position_limit_pct=args.base_position_limit,
    )

    metrics = engine.run_backtest()
    values = engine.get_portfolio_values()

    # Minimal terminal output (no plots)
    if values:
        print(f"\n{Fore.WHITE}{Style.BRIGHT}引擎執行完成{Style.RESET_ALL}")
        last_value = values[-1]["Portfolio Value"]
        start_value = values[0]["Portfolio Value"]
        total_return = (last_value / start_value - 1.0) * 100.0 if start_value else 0.0
        print(f"總報酬率：{Fore.GREEN if total_return >= 0 else Fore.RED}{total_return:.2f}%{Style.RESET_ALL}")
    if metrics.get("sharpe_ratio") is not None:
        print(f"夏普值：{metrics['sharpe_ratio']:.2f}")
    if metrics.get("sortino_ratio") is not None:
        print(f"索提諾值：{metrics['sortino_ratio']:.2f}")
    if metrics.get("max_drawdown") is not None:
        md = abs(metrics["max_drawdown"]) if metrics["max_drawdown"] is not None else 0.0
        if metrics.get("max_drawdown_date"):
            print(f"最大回撤：{md:.2f}%（日期：{metrics['max_drawdown_date']}）")
        else:
            print(f"最大回撤：{md:.2f}%")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())




