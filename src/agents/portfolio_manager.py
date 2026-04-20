import json
import time
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate

from src.graph.state import AgentState, show_agent_reasoning
from pydantic import BaseModel, Field
from typing_extensions import Literal
from src.utils.progress import progress
from src.utils.llm import call_llm


class PortfolioDecision(BaseModel):
    action: Literal["buy", "sell", "short", "cover", "hold"]
    quantity: int = Field(description="Number of shares to trade")
    confidence: int = Field(description="Confidence 0-100")
    reasoning: str = Field(description="決策理由（繁體中文）")


class PortfolioManagerOutput(BaseModel):
    decisions: dict[str, PortfolioDecision] = Field(description="Dictionary of ticker to trading decisions")


ACTION_TO_SIGNAL = {
    "buy": "BULLISH",
    "cover": "BULLISH",
    "sell": "BEARISH",
    "short": "BEARISH",
    "hold": "NEUTRAL",
}

ACTION_TO_LABEL = {
    "buy": "買進",
    "cover": "回補",
    "sell": "賣出",
    "short": "放空",
    "hold": "持有",
}


def _normalize_signal(signal: str | None) -> str:
    value = (signal or "").strip().upper()
    if value in {"BULLISH", "BEARISH", "NEUTRAL"}:
        return value
    return "NEUTRAL"


def _normalize_confidence(confidence: int | float | str | None) -> float:
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, value))


def _count_signals(ticker_signals: dict[str, dict]) -> tuple[int, int, int]:
    bullish = 0
    bearish = 0
    neutral = 0
    for payload in ticker_signals.values():
        signal = _normalize_signal(payload.get("sig") or payload.get("signal"))
        if signal == "BULLISH":
            bullish += 1
        elif signal == "BEARISH":
            bearish += 1
        else:
            neutral += 1
    return bullish, bearish, neutral


def _compute_consensus_confidence(action: str, ticker_signals: dict[str, dict]) -> int:
    target_signal = ACTION_TO_SIGNAL.get(action, "NEUTRAL")
    if not ticker_signals:
        return 0

    total_weight = 0.0
    support_weight = 0.0
    for payload in ticker_signals.values():
        signal = _normalize_signal(payload.get("sig") or payload.get("signal"))
        weight = _normalize_confidence(payload.get("conf") if "conf" in payload else payload.get("confidence")) / 100.0
        total_weight += weight
        if signal == target_signal:
            support_weight += weight

    if total_weight <= 0:
        return 0
    return int(round((support_weight / total_weight) * 100))


def _build_reasoning(action: str, ticker_signals: dict[str, dict], forced_hold: bool = False) -> str:
    if forced_hold:
        return "受風險與倉位限制，當前無可執行交易，維持持有。"

    bullish, bearish, neutral = _count_signals(ticker_signals)
    action_label = ACTION_TO_LABEL.get(action, action)
    return f"分析師訊號：看多{bullish}、看空{bearish}、中立{neutral}；綜合後採取{action_label}。"


##### Portfolio Management Agent #####
def portfolio_management_agent(state: AgentState, agent_id: str = "portfolio_manager"):
    """Makes final trading decisions and generates orders for multiple tickers"""

    portfolio = state["data"]["portfolio"]
    analyst_signals = state["data"]["analyst_signals"]
    tickers = state["data"]["tickers"]

    position_limits = {}
    current_prices = {}
    max_shares = {}
    signals_by_ticker = {}
    for ticker in tickers:
        progress.update_status(agent_id, ticker, "整理分析代理訊號")

        # Find the corresponding risk manager for this portfolio manager
        if agent_id.startswith("portfolio_manager_"):
            suffix = agent_id.split('_')[-1]
            risk_manager_id = f"risk_management_agent_{suffix}"
        else:
            risk_manager_id = "risk_management_agent"  # Fallback for CLI

        risk_data = analyst_signals.get(risk_manager_id, {}).get(ticker, {})
        position_limits[ticker] = risk_data.get("remaining_position_limit", 0.0)
        current_prices[ticker] = float(risk_data.get("current_price", 0.0))

        # Calculate maximum shares allowed based on position limit and price
        if current_prices[ticker] > 0:
            max_shares[ticker] = int(position_limits[ticker] // current_prices[ticker])
        else:
            max_shares[ticker] = 0

        # Compress analyst signals to {sig, conf}
        ticker_signals = {}
        for agent, signals in analyst_signals.items():
            if not agent.startswith("risk_management_agent") and ticker in signals:
                sig = signals[ticker].get("signal")
                conf = signals[ticker].get("confidence")
                if sig is not None and conf is not None:
                    ticker_signals[agent] = {"sig": sig, "conf": conf}
        signals_by_ticker[ticker] = ticker_signals

    state["data"]["current_prices"] = current_prices

    progress.update_status(agent_id, None, "生成交易決策")

    result = generate_trading_decision(
        tickers=tickers,
        signals_by_ticker=signals_by_ticker,
        current_prices=current_prices,
        max_shares=max_shares,
        portfolio=portfolio,
        agent_id=agent_id,
        state=state,
    )
    message = HumanMessage(
        content=json.dumps({ticker: decision.model_dump() for ticker, decision in result.decisions.items()}),
        name=agent_id,
    )

    if state["metadata"]["show_reasoning"]:
        show_agent_reasoning(
            {ticker: decision.model_dump() for ticker, decision in result.decisions.items()},
            "投資組合經理",
        )

    progress.update_status(agent_id, None, "完成")

    return {
        "messages": state["messages"] + [message],
        "data": state["data"],
    }


def compute_allowed_actions(
        tickers: list[str],
        current_prices: dict[str, float],
        max_shares: dict[str, int],
        portfolio: dict[str, float],
) -> dict[str, dict[str, int]]:
    """Compute allowed actions and max quantities for each ticker deterministically."""
    allowed = {}
    cash = float(portfolio.get("cash", 0.0))
    positions = portfolio.get("positions", {}) or {}
    margin_requirement = float(portfolio.get("margin_requirement", 0.5))
    margin_used = float(portfolio.get("margin_used", 0.0))
    equity = float(portfolio.get("equity", cash))

    for ticker in tickers:
        price = float(current_prices.get(ticker, 0.0))
        pos = positions.get(
            ticker,
            {"long": 0, "long_cost_basis": 0.0, "short": 0, "short_cost_basis": 0.0},
        )
        long_shares = int(pos.get("long", 0) or 0)
        short_shares = int(pos.get("short", 0) or 0)
        max_qty = int(max_shares.get(ticker, 0) or 0)

        # Start with zeros
        actions = {"buy": 0, "sell": 0, "short": 0, "cover": 0, "hold": 0}

        # Long side
        if long_shares > 0:
            actions["sell"] = long_shares
        if cash > 0 and price > 0:
            max_buy_cash = int(cash // price)
            max_buy = max(0, min(max_qty, max_buy_cash))
            if max_buy > 0:
                actions["buy"] = max_buy

        # Short side
        if short_shares > 0:
            actions["cover"] = short_shares
        if price > 0 and max_qty > 0:
            if margin_requirement <= 0.0:
                # If margin requirement is zero or unset, only cap by max_qty
                max_short = max_qty
            else:
                available_margin = max(0.0, (equity / margin_requirement) - margin_used)
                max_short_margin = int(available_margin // price)
                max_short = max(0, min(max_qty, max_short_margin))
            if max_short > 0:
                actions["short"] = max_short

        # Hold always valid
        actions["hold"] = 0

        # Prune zero-capacity actions to reduce tokens, keep hold
        pruned = {"hold": 0}
        for k, v in actions.items():
            if k != "hold" and v > 0:
                pruned[k] = v

        allowed[ticker] = pruned

    return allowed


def _compact_signals(signals_by_ticker: dict[str, dict]) -> dict[str, dict]:
    """Keep only {agent: {sig, conf}} and drop empty agents."""
    out = {}
    for t, agents in signals_by_ticker.items():
        if not agents:
            out[t] = {}
            continue
        compact = {}
        for agent, payload in agents.items():
            sig = payload.get("sig") or payload.get("signal")
            conf = payload.get("conf") if "conf" in payload else payload.get("confidence")
            if sig is not None and conf is not None:
                compact[agent] = {"sig": sig, "conf": conf}
        out[t] = compact
    return out


def generate_trading_decision(
        tickers: list[str],
        signals_by_ticker: dict[str, dict],
        current_prices: dict[str, float],
        max_shares: dict[str, int],
        portfolio: dict[str, float],
        agent_id: str,
        state: AgentState,
) -> PortfolioManagerOutput:
    """Get decisions from the LLM with deterministic constraints and a minimal prompt."""

    # Deterministic constraints
    allowed_actions_full = compute_allowed_actions(tickers, current_prices, max_shares, portfolio)

    # Pre-fill pure holds to avoid sending them to the LLM at all
    prefilled_decisions: dict[str, PortfolioDecision] = {}
    tickers_for_llm: list[str] = []
    for t in tickers:
        aa = allowed_actions_full.get(t, {"hold": 0})
        # If only 'hold' key exists, there is no trade possible
        if set(aa.keys()) == {"hold"}:
            prefilled_decisions[t] = PortfolioDecision(
                action="hold",
                quantity=0,
                confidence=100,
                reasoning=_build_reasoning("hold", signals_by_ticker.get(t, {}), forced_hold=True),
            )
        else:
            tickers_for_llm.append(t)

    if not tickers_for_llm:
        return PortfolioManagerOutput(decisions=prefilled_decisions)

    # Build compact payloads only for tickers sent to LLM
    compact_signals = _compact_signals({t: signals_by_ticker.get(t, {}) for t in tickers_for_llm})
    compact_allowed = {t: allowed_actions_full[t] for t in tickers_for_llm}

    # Minimal prompt template
    template = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "你是投資組合經理。\n"
                "每檔股票輸入包含：分析代理訊號、以及已驗證的可執行动作與最大數量。\n"
                "請為每檔股票只選一個可執行动作，且 quantity 不得超過該動作上限。\n"
                "reasoning 必須使用繁體中文，且非常精簡（100 字內）。\n"
                "不要寫現金或保證金計算過程。只回傳 JSON。"
            ),
            (
                "human",
                "訊號：\n{signals}\n\n"
                "可執行上限：\n{allowed}\n\n"
                "輸出格式：\n"
                "{{\n"
                '  "decisions": {{\n'
                '    "TICKER": {{"action":"...","quantity":int,"confidence":int,"reasoning":"..."}}\n'
                "  }}\n"
                "}}"
            ),
        ]
    )

    prompt_data = {
        "signals": json.dumps(compact_signals, separators=(",", ":"), ensure_ascii=False),
        "allowed": json.dumps(compact_allowed, separators=(",", ":"), ensure_ascii=False),
    }
    prompt = template.invoke(prompt_data)

    # Default factory fills remaining tickers as hold if the LLM fails
    def create_default_portfolio_output():
        # start from prefilled
        decisions = dict(prefilled_decisions)
        for t in tickers_for_llm:
            decisions[t] = PortfolioDecision(
                action="hold", quantity=0, confidence=0.0, reasoning="預設決策：持有"
            )
        return PortfolioManagerOutput(decisions=decisions)

    llm_out = call_llm(
        prompt=prompt,
        pydantic_model=PortfolioManagerOutput,
        agent_name=agent_id,
        state=state,
        default_factory=create_default_portfolio_output,
    )

    # Sanitize model output against allowed actions and compute confidence from analyst consensus.
    sanitized_decisions: dict[str, PortfolioDecision] = {}
    for t in tickers_for_llm:
        allowed_for_ticker = compact_allowed.get(t, {"hold": 0})
        llm_decision = llm_out.decisions.get(t)

        action = "hold"
        quantity = 0
        if llm_decision is not None:
            candidate_action = str(llm_decision.action).lower()
            if candidate_action in allowed_for_ticker:
                action = candidate_action
                quantity = int(max(0, llm_decision.quantity))

        if action == "hold":
            quantity = 0
        else:
            quantity = min(quantity, int(allowed_for_ticker.get(action, 0)))
            if quantity <= 0:
                action = "hold"
                quantity = 0

        confidence = _compute_consensus_confidence(action, compact_signals.get(t, {}))
        reasoning = _build_reasoning(action, compact_signals.get(t, {}))
        sanitized_decisions[t] = PortfolioDecision(
            action=action,
            quantity=quantity,
            confidence=confidence,
            reasoning=reasoning,
        )

    # Merge prefilled holds with sanitized LLM results
    merged = dict(prefilled_decisions)
    merged.update(sanitized_decisions)
    return PortfolioManagerOutput(decisions=merged)
