from __future__ import annotations

import datetime
import logging
import math
import time

import pandas as pd
import requests
import yfinance as yf

from src.data.cache import get_cache
from src.data.models import (
    CompanyNews,
    FinancialMetrics,
    InsiderTrade,
    LineItem,
    Price,
)

logger = logging.getLogger(__name__)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("curl_cffi").setLevel(logging.CRITICAL)

# Global cache instance
_cache = get_cache()
_ticker_resolution_cache: dict[str, str] = {}


def _make_api_request(url: str, headers: dict, method: str = "GET", json_data: dict = None, max_retries: int = 3) -> requests.Response:
    """
    Backward-compatible request helper retained for tests and legacy integrations.
    """
    for attempt in range(max_retries + 1):  # +1 for initial attempt
        if method.upper() == "POST":
            response = requests.post(url, headers=headers, json=json_data)
        else:
            response = requests.get(url, headers=headers)

        if response.status_code == 429 and attempt < max_retries:
            delay = 60 + (30 * attempt)
            print(f"Rate limited (429). Attempt {attempt + 1}/{max_retries + 1}. Waiting {delay}s before retrying...")
            time.sleep(delay)
            continue

        return response


def _candidate_tickers(ticker: str) -> list[str]:
    normalized = ticker.strip().upper()
    if normalized.endswith(".TW"):
        base = normalized[:-3]
        candidates = [normalized, f"{base}.TWO", base]
    elif normalized.endswith(".TWO"):
        base = normalized[:-4]
        candidates = [normalized, f"{base}.TW", base]
    elif normalized.isdigit() and len(normalized) == 4:
        candidates = [f"{normalized}.TW", f"{normalized}.TWO", normalized]
    else:
        candidates = [normalized]

    preferred = _ticker_resolution_cache.get(normalized)
    if preferred:
        ordered = [preferred] + [c for c in candidates if c != preferred]
        return ordered
    return candidates


def _remember_ticker_resolution(ticker: str, resolved: str) -> None:
    normalized = ticker.strip().upper()
    resolved_normalized = resolved.strip().upper()
    _ticker_resolution_cache[normalized] = resolved_normalized

    if normalized.endswith(".TW") or normalized.endswith(".TWO"):
        base = normalized.split(".")[0]
        _ticker_resolution_cache.setdefault(base, resolved_normalized)
    elif normalized.isdigit() and len(normalized) == 4:
        _ticker_resolution_cache.setdefault(f"{normalized}.TW", resolved_normalized)
        _ticker_resolution_cache.setdefault(f"{normalized}.TWO", resolved_normalized)


def _safe_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, pd.Series):
        cleaned = value.dropna()
        if cleaned.empty:
            return None
        value = cleaned.iloc[0]
    elif isinstance(value, (list, tuple)):
        if not value:
            return None
        value = value[0]
    try:
        is_na = pd.isna(value)
        if isinstance(is_na, (pd.Series, list, tuple)) or hasattr(is_na, "shape"):
            return None
        if bool(is_na):
            return None
    except TypeError:
        pass
    try:
        out = float(value)
        if math.isnan(out) or math.isinf(out):
            return None
        return out
    except (TypeError, ValueError):
        return None


def _safe_int(value) -> int | None:
    as_float = _safe_float(value)
    if as_float is None:
        return None
    try:
        return int(as_float)
    except (TypeError, ValueError):
        return None


def _compute_growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / abs(previous)


def _row_value(df: pd.DataFrame, column, aliases: list[str]) -> float | None:
    if df is None or df.empty:
        return None
    resolved_column = column
    if resolved_column not in df.columns:
        try:
            target_ts = pd.to_datetime(column, errors="coerce")
            if not pd.isna(target_ts):
                target_day = target_ts.date()
                for candidate in df.columns:
                    candidate_ts = pd.to_datetime(candidate, errors="coerce")
                    if pd.isna(candidate_ts):
                        continue
                    if candidate_ts.date() == target_day:
                        resolved_column = candidate
                        break
                else:
                    return None
            else:
                return None
        except Exception:
            return None
    lowered_index = {str(idx).strip().lower(): idx for idx in df.index}
    for alias in aliases:
        idx = lowered_index.get(alias.strip().lower())
        if idx is None:
            continue
        value = _safe_float(df.at[idx, resolved_column])
        if value is not None:
            return value
    return None


def _sorted_statement_columns(dataframes: list[pd.DataFrame], end_date: str, limit: int) -> list:
    end = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
    dated_columns: list[tuple[object, datetime.datetime]] = []
    seen = set()

    for df in dataframes:
        if df is None or df.empty:
            continue
        for col in df.columns:
            if col in seen:
                continue
            parsed = pd.to_datetime(col, errors="coerce")
            if pd.isna(parsed):
                continue
            if parsed.date() <= end:
                dated_columns.append((col, parsed.to_pydatetime()))
                seen.add(col)

    dated_columns.sort(key=lambda x: x[1], reverse=True)
    return [c for c, _ in dated_columns[:limit]]


def _resolve_ticker_with_history(ticker: str) -> tuple[str, yf.Ticker]:
    for candidate in _candidate_tickers(ticker):
        stock = yf.Ticker(candidate)
        try:
            history = stock.history(period="1mo", interval="1d", auto_adjust=False)
        except Exception:
            logger.debug("history lookup failed for candidate %s", candidate, exc_info=True)
            continue
        if not history.empty:
            _remember_ticker_resolution(ticker, candidate)
            return candidate, stock
    fallback = _candidate_tickers(ticker)[0]
    return fallback, yf.Ticker(fallback)


def _download_prices(ticker: str, start_date: str, end_date: str) -> tuple[str, pd.DataFrame]:
    end_exclusive = (datetime.datetime.strptime(end_date, "%Y-%m-%d") + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    for candidate in _candidate_tickers(ticker):
        try:
            prices = yf.download(
                candidate,
                start=start_date,
                end=end_exclusive,
                interval="1d",
                auto_adjust=False,
                progress=False,
                threads=False,
            )
        except Exception:
            logger.debug("price download failed for candidate %s", candidate, exc_info=True)
            continue
        if not prices.empty:
            _remember_ticker_resolution(ticker, candidate)
            return candidate, prices
    return _candidate_tickers(ticker)[0], pd.DataFrame()


def _safe_stock_info(stock: yf.Ticker) -> dict:
    try:
        info = stock.info
    except (TypeError, AttributeError):
        return {}
    return info if isinstance(info, dict) else {}


def _collect_snapshots(ticker: str, end_date: str, period: str, limit: int) -> tuple[str, dict, list[dict]]:
    resolved, stock = _resolve_ticker_with_history(ticker)
    info = _safe_stock_info(stock)

    if period == "annual":
        income = stock.income_stmt
        balance = stock.balance_sheet
        cashflow = stock.cashflow
        period_name = "annual"
    else:
        income = stock.quarterly_income_stmt
        balance = stock.quarterly_balance_sheet
        cashflow = stock.quarterly_cashflow
        period_name = "ttm"

    columns = _sorted_statement_columns([income, balance, cashflow], end_date=end_date, limit=limit)
    if not columns:
        latest_price = _safe_float(info.get("regularMarketPrice")) or _safe_float(info.get("currentPrice"))
        market_cap = _safe_float(info.get("marketCap"))
        enterprise_value = _safe_float(info.get("enterpriseValue"))
        return resolved, info, [
            {
                "ticker": resolved,
                "report_period": end_date,
                "period": period_name,
                "currency": info.get("currency") or "USD",
                "market_cap": market_cap,
                "enterprise_value": enterprise_value,
                "price": latest_price,
                "shares_outstanding": _safe_float(info.get("sharesOutstanding")),
            }
        ]

    snapshots: list[dict] = []
    shares_outstanding = _safe_float(info.get("sharesOutstanding"))
    market_cap = _safe_float(info.get("marketCap"))
    enterprise_value = _safe_float(info.get("enterpriseValue"))
    price_to_book = _safe_float(info.get("priceToBook"))
    trailing_pe = _safe_float(info.get("trailingPE"))
    trailing_peg = _safe_float(info.get("pegRatio"))

    for col in columns:
        report_dt = pd.to_datetime(col, errors="coerce")
        report_period = report_dt.strftime("%Y-%m-%d") if not pd.isna(report_dt) else end_date

        revenue = _row_value(income, col, ["Total Revenue", "Operating Revenue", "Revenue"])
        net_income = _row_value(income, col, ["Net Income", "Net Income Common Stockholders"])
        gross_profit = _row_value(income, col, ["Gross Profit"])
        operating_income = _row_value(income, col, ["Operating Income"])
        ebit = _row_value(income, col, ["EBIT", "Ebit"])
        ebitda = _row_value(income, col, ["EBITDA", "Ebitda"])
        interest_expense = _row_value(income, col, ["Interest Expense", "Net Interest Income"])
        operating_expense = _row_value(income, col, ["Operating Expense", "Total Operating Expenses"])
        research_and_development = _row_value(income, col, ["Research And Development", "Research Development"])

        total_assets = _row_value(balance, col, ["Total Assets"])
        total_liabilities = _row_value(balance, col, ["Total Liabilities Net Minority Interest", "Total Liabilities"])
        shareholders_equity = _row_value(balance, col, ["Stockholders Equity", "Total Equity Gross Minority Interest", "Common Stock Equity"])
        current_assets = _row_value(balance, col, ["Current Assets", "Total Current Assets"])
        current_liabilities = _row_value(balance, col, ["Current Liabilities", "Total Current Liabilities"])
        total_debt = _row_value(balance, col, ["Total Debt", "Long Term Debt And Capital Lease Obligation", "Long Term Debt"])
        cash_and_equivalents = _row_value(balance, col, ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"])
        goodwill_and_intangible_assets = _row_value(balance, col, ["Goodwill And Other Intangible Assets", "Goodwill"])

        free_cash_flow = _row_value(cashflow, col, ["Free Cash Flow"])
        capex = _row_value(cashflow, col, ["Capital Expenditure"])
        depreciation_and_amortization = _row_value(cashflow, col, ["Depreciation And Amortization", "Depreciation Amortization Depletion"])
        dividends = _row_value(cashflow, col, ["Cash Dividends Paid"])
        issuance_stock = _row_value(cashflow, col, ["Issuance Of Capital Stock"])
        repurchase_stock = _row_value(cashflow, col, ["Repurchase Of Capital Stock"])
        issuance_or_purchase = None
        if issuance_stock is not None or repurchase_stock is not None:
            issuance_or_purchase = (issuance_stock or 0.0) + (repurchase_stock or 0.0)

        working_capital = None
        if current_assets is not None and current_liabilities is not None:
            working_capital = current_assets - current_liabilities

        roe = None
        if net_income is not None and shareholders_equity:
            roe = net_income / shareholders_equity

        roa = None
        if net_income is not None and total_assets:
            roa = net_income / total_assets

        net_margin = None
        operating_margin = None
        gross_margin = None
        if revenue:
            if net_income is not None:
                net_margin = net_income / revenue
            if operating_income is not None:
                operating_margin = operating_income / revenue
            if gross_profit is not None:
                gross_margin = gross_profit / revenue

        debt_to_equity = None
        debt_to_assets = None
        if total_debt is not None and shareholders_equity:
            debt_to_equity = total_debt / shareholders_equity
        if total_debt is not None and total_assets:
            debt_to_assets = total_debt / total_assets

        current_ratio = None
        if current_assets is not None and current_liabilities:
            current_ratio = current_assets / current_liabilities

        quick_ratio = None
        cash_ratio = None
        if cash_and_equivalents is not None and current_liabilities:
            cash_ratio = cash_and_equivalents / current_liabilities
            quick_ratio = cash_and_equivalents / current_liabilities

        interest_coverage = None
        if operating_income is not None and interest_expense not in (None, 0):
            interest_coverage = abs(operating_income / interest_expense)

        eps = None
        if net_income is not None and shares_outstanding:
            eps = net_income / shares_outstanding

        book_value_per_share = None
        if shareholders_equity is not None and shares_outstanding:
            book_value_per_share = shareholders_equity / shares_outstanding

        fcf_per_share = None
        if free_cash_flow is not None and shares_outstanding:
            fcf_per_share = free_cash_flow / shares_outstanding

        price = None
        if market_cap is not None and shares_outstanding:
            price = market_cap / shares_outstanding
        if price is None:
            price = _safe_float(info.get("regularMarketPrice")) or _safe_float(info.get("currentPrice"))

        ps_ratio = None
        if market_cap is not None and revenue:
            ps_ratio = market_cap / revenue

        pe_ratio = None
        if market_cap is not None and net_income not in (None, 0):
            pe_ratio = market_cap / net_income
        if pe_ratio is None:
            pe_ratio = trailing_pe

        pb_ratio = None
        if market_cap is not None and shareholders_equity not in (None, 0):
            pb_ratio = market_cap / shareholders_equity
        if pb_ratio is None:
            pb_ratio = price_to_book

        ev_to_ebitda = None
        if enterprise_value is not None and ebitda not in (None, 0):
            ev_to_ebitda = enterprise_value / ebitda

        ev_to_revenue = None
        if enterprise_value is not None and revenue not in (None, 0):
            ev_to_revenue = enterprise_value / revenue

        fcf_yield = None
        if free_cash_flow is not None and market_cap not in (None, 0):
            fcf_yield = free_cash_flow / market_cap

        roic = None
        if operating_income is not None and total_debt is not None and shareholders_equity is not None and cash_and_equivalents is not None:
            invested_capital = total_debt + shareholders_equity - cash_and_equivalents
            if invested_capital:
                roic = operating_income / invested_capital

        snapshots.append(
            {
                "ticker": resolved,
                "report_period": report_period,
                "period": period_name,
                "currency": info.get("currency") or "USD",
                "market_cap": market_cap,
                "enterprise_value": enterprise_value,
                "price_to_earnings_ratio": pe_ratio,
                "price_to_book_ratio": pb_ratio,
                "price_to_sales_ratio": ps_ratio,
                "enterprise_value_to_ebitda_ratio": ev_to_ebitda,
                "enterprise_value_to_revenue_ratio": ev_to_revenue,
                "free_cash_flow_yield": fcf_yield,
                "peg_ratio": trailing_peg,
                "gross_margin": gross_margin,
                "operating_margin": operating_margin,
                "net_margin": net_margin,
                "return_on_equity": roe,
                "return_on_assets": roa,
                "return_on_invested_capital": roic,
                "asset_turnover": (revenue / total_assets) if (revenue is not None and total_assets not in (None, 0)) else None,
                "inventory_turnover": None,
                "receivables_turnover": None,
                "days_sales_outstanding": None,
                "operating_cycle": None,
                "working_capital_turnover": (revenue / working_capital) if (revenue is not None and working_capital not in (None, 0)) else None,
                "current_ratio": current_ratio,
                "quick_ratio": quick_ratio,
                "cash_ratio": cash_ratio,
                "operating_cash_flow_ratio": None,
                "debt_to_equity": debt_to_equity,
                "debt_to_assets": debt_to_assets,
                "interest_coverage": interest_coverage,
                "revenue": revenue,
                "net_income": net_income,
                "gross_profit": gross_profit,
                "operating_income": operating_income,
                "ebit": ebit,
                "ebitda": ebitda,
                "free_cash_flow": free_cash_flow,
                "capital_expenditure": capex,
                "depreciation_and_amortization": depreciation_and_amortization,
                "total_assets": total_assets,
                "total_liabilities": total_liabilities,
                "shareholders_equity": shareholders_equity,
                "current_assets": current_assets,
                "current_liabilities": current_liabilities,
                "total_debt": total_debt,
                "cash_and_equivalents": cash_and_equivalents,
                "goodwill_and_intangible_assets": goodwill_and_intangible_assets,
                "operating_expense": operating_expense,
                "research_and_development": research_and_development,
                "interest_expense": interest_expense,
                "outstanding_shares": shares_outstanding,
                "issuance_or_purchase_of_equity_shares": issuance_or_purchase,
                "dividends_and_other_cash_distributions": dividends,
                "working_capital": working_capital,
                "earnings_per_share": eps,
                "book_value_per_share": book_value_per_share,
                "free_cash_flow_per_share": fcf_per_share,
            }
        )

    return resolved, info, snapshots


def get_prices(ticker: str, start_date: str, end_date: str, api_key: str = None) -> list[Price]:
    """Fetch daily OHLCV data from yfinance."""
    cache_key = f"{ticker}_{start_date}_{end_date}"
    if cached_data := _cache.get_prices(cache_key):
        return [Price(**price) for price in cached_data]

    resolved, price_df = _download_prices(ticker, start_date, end_date)
    if price_df.empty:
        logger.warning("No price data from yfinance for %s", ticker)
        return []

    if isinstance(price_df.columns, pd.MultiIndex):
        level0 = set(price_df.columns.get_level_values(0))
        level1 = set(price_df.columns.get_level_values(1))
        if {"Open", "Close", "High", "Low", "Volume"}.issubset(level0):
            price_df = price_df.droplevel(1, axis=1)
        elif {"Open", "Close", "High", "Low", "Volume"}.issubset(level1):
            price_df = price_df.droplevel(0, axis=1)

    prices: list[Price] = []
    for idx, row in price_df.iterrows():
        timestamp = pd.to_datetime(idx, errors="coerce")
        if pd.isna(timestamp):
            continue
        ts = timestamp.tz_localize(None) if timestamp.tzinfo else timestamp
        open_price = _safe_float(row.get("Open"))
        close_price = _safe_float(row.get("Close"))
        high_price = _safe_float(row.get("High"))
        low_price = _safe_float(row.get("Low"))
        volume = _safe_int(row.get("Volume"))
        if None in (open_price, close_price, high_price, low_price, volume):
            continue
        prices.append(
            Price(
                open=open_price,
                close=close_price,
                high=high_price,
                low=low_price,
                volume=volume,
                time=ts.strftime("%Y-%m-%dT00:00:00Z"),
            )
        )

    if not prices:
        return []

    _cache.set_prices(cache_key, [p.model_dump() for p in prices])
    logger.debug("Loaded %d yfinance bars for %s (resolved as %s)", len(prices), ticker, resolved)
    return prices


def get_financial_metrics(
    ticker: str,
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key: str = None,
) -> list[FinancialMetrics]:
    """Fetch normalized financial metrics from yfinance statements/info."""
    cache_key = f"{ticker}_{period}_{end_date}_{limit}"
    if cached_data := _cache.get_financial_metrics(cache_key):
        return [FinancialMetrics(**metric) for metric in cached_data]

    _, _, snapshots = _collect_snapshots(ticker=ticker, end_date=end_date, period=period, limit=limit)
    if not snapshots:
        return []

    metrics: list[FinancialMetrics] = []
    for idx, snap in enumerate(snapshots):
        previous = snapshots[idx + 1] if idx + 1 < len(snapshots) else None
        metric = FinancialMetrics(
            ticker=snap.get("ticker"),
            report_period=snap.get("report_period"),
            period=snap.get("period"),
            currency=snap.get("currency"),
            market_cap=snap.get("market_cap"),
            enterprise_value=snap.get("enterprise_value"),
            price_to_earnings_ratio=snap.get("price_to_earnings_ratio"),
            price_to_book_ratio=snap.get("price_to_book_ratio"),
            price_to_sales_ratio=snap.get("price_to_sales_ratio"),
            enterprise_value_to_ebitda_ratio=snap.get("enterprise_value_to_ebitda_ratio"),
            enterprise_value_to_revenue_ratio=snap.get("enterprise_value_to_revenue_ratio"),
            free_cash_flow_yield=snap.get("free_cash_flow_yield"),
            peg_ratio=snap.get("peg_ratio"),
            gross_margin=snap.get("gross_margin"),
            operating_margin=snap.get("operating_margin"),
            net_margin=snap.get("net_margin"),
            return_on_equity=snap.get("return_on_equity"),
            return_on_assets=snap.get("return_on_assets"),
            return_on_invested_capital=snap.get("return_on_invested_capital"),
            asset_turnover=snap.get("asset_turnover"),
            inventory_turnover=snap.get("inventory_turnover"),
            receivables_turnover=snap.get("receivables_turnover"),
            days_sales_outstanding=snap.get("days_sales_outstanding"),
            operating_cycle=snap.get("operating_cycle"),
            working_capital_turnover=snap.get("working_capital_turnover"),
            current_ratio=snap.get("current_ratio"),
            quick_ratio=snap.get("quick_ratio"),
            cash_ratio=snap.get("cash_ratio"),
            operating_cash_flow_ratio=snap.get("operating_cash_flow_ratio"),
            debt_to_equity=snap.get("debt_to_equity"),
            debt_to_assets=snap.get("debt_to_assets"),
            interest_coverage=snap.get("interest_coverage"),
            revenue_growth=_compute_growth(snap.get("revenue"), previous.get("revenue") if previous else None),
            earnings_growth=_compute_growth(snap.get("net_income"), previous.get("net_income") if previous else None),
            book_value_growth=_compute_growth(snap.get("shareholders_equity"), previous.get("shareholders_equity") if previous else None),
            earnings_per_share_growth=_compute_growth(snap.get("earnings_per_share"), previous.get("earnings_per_share") if previous else None),
            free_cash_flow_growth=_compute_growth(snap.get("free_cash_flow"), previous.get("free_cash_flow") if previous else None),
            operating_income_growth=_compute_growth(snap.get("operating_income"), previous.get("operating_income") if previous else None),
            ebitda_growth=_compute_growth(snap.get("ebitda"), previous.get("ebitda") if previous else None),
            payout_ratio=(
                abs(snap.get("dividends_and_other_cash_distributions", 0) or 0) / abs(snap.get("net_income", 1) or 1)
                if snap.get("dividends_and_other_cash_distributions") not in (None, 0)
                and snap.get("net_income") not in (None, 0)
                else None
            ),
            earnings_per_share=snap.get("earnings_per_share"),
            book_value_per_share=snap.get("book_value_per_share"),
            free_cash_flow_per_share=snap.get("free_cash_flow_per_share"),
        )
        metrics.append(metric)

    _cache.set_financial_metrics(cache_key, [m.model_dump() for m in metrics])
    return metrics


def search_line_items(
    ticker: str,
    line_items: list[str],
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key: str = None,
) -> list[LineItem]:
    """Return requested line items from yfinance statements in normalized shape."""
    cache_key = f"{ticker}_{period}_{end_date}_{limit}"
    cached = _cache.get_line_items(cache_key)
    if cached:
        return [LineItem(**item) for item in cached[:limit]]

    _, _, snapshots = _collect_snapshots(ticker=ticker, end_date=end_date, period=period, limit=limit)
    if not snapshots:
        return []

    payload: list[LineItem] = []
    for snap in snapshots:
        row = {
            "ticker": snap["ticker"],
            "report_period": snap["report_period"],
            "period": snap["period"],
            "currency": snap["currency"],
        }
        for item in line_items:
            row[item] = snap.get(item)
        payload.append(LineItem(**row))

    _cache.set_line_items(cache_key, [item.model_dump() for item in payload])
    return payload[:limit]


def get_insider_trades(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str = None,
) -> list[InsiderTrade]:
    """Fetch insider trades from yfinance insider transaction feed."""
    cache_key = f"{ticker}_{start_date or 'none'}_{end_date}_{limit}"
    if cached_data := _cache.get_insider_trades(cache_key):
        return [InsiderTrade(**trade) for trade in cached_data]

    resolved, stock = _resolve_ticker_with_history(ticker)
    tx = stock.insider_transactions
    if tx is None or tx.empty:
        return []

    end = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
    start = datetime.datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
    info = _safe_stock_info(stock)
    company_name = info.get("longName")

    trades: list[InsiderTrade] = []
    for _, row in tx.iterrows():
        date_val = pd.to_datetime(row.get("Start Date"), errors="coerce")
        if pd.isna(date_val):
            continue
        filing_date = date_val.strftime("%Y-%m-%dT00:00:00Z")
        filing_day = date_val.date()
        if filing_day > end:
            continue
        if start and filing_day < start:
            continue

        shares = _safe_float(row.get("Shares"))
        value = _safe_float(row.get("Value"))
        transaction_label = str(row.get("Transaction", "")).lower()
        if shares is not None:
            if "sale" in transaction_label or "sell" in transaction_label:
                shares = -abs(shares)
            elif "buy" in transaction_label or "purchase" in transaction_label:
                shares = abs(shares)

        trades.append(
            InsiderTrade(
                ticker=resolved,
                issuer=company_name,
                name=str(row.get("Insider")) if row.get("Insider") is not None else None,
                title=str(row.get("Position")) if row.get("Position") is not None else None,
                is_board_director=None,
                transaction_date=filing_date,
                transaction_shares=shares,
                transaction_price_per_share=None,
                transaction_value=value,
                shares_owned_before_transaction=None,
                shares_owned_after_transaction=None,
                security_title=str(row.get("Transaction")) if row.get("Transaction") is not None else None,
                filing_date=filing_date,
            )
        )
        if len(trades) >= limit:
            break

    _cache.set_insider_trades(cache_key, [trade.model_dump() for trade in trades])
    return trades


def get_company_news(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str = None,
) -> list[CompanyNews]:
    """Fetch company news from yfinance news feed."""
    cache_key = f"{ticker}_{start_date or 'none'}_{end_date}_{limit}"
    if cached_data := _cache.get_company_news(cache_key):
        return [CompanyNews(**news) for news in cached_data]

    resolved, stock = _resolve_ticker_with_history(ticker)
    try:
        items = stock.news or []
    except (TypeError, AttributeError):
        items = []
    if not items:
        return []

    end = datetime.datetime.strptime(end_date, "%Y-%m-%d").date()
    start = datetime.datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None

    news: list[CompanyNews] = []
    for item in items:
        published = item.get("providerPublishTime")
        if published is None:
            continue
        dt = datetime.datetime.fromtimestamp(published, tz=datetime.timezone.utc)
        day = dt.date()
        if day > end:
            continue
        if start and day < start:
            continue

        title = item.get("title")
        source = item.get("publisher")
        url = item.get("link")
        if not title or not source or not url:
            continue

        news.append(
            CompanyNews(
                ticker=resolved,
                title=title,
                author=None,
                source=source,
                date=dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                url=url,
                sentiment=None,
            )
        )
        if len(news) >= limit:
            break

    _cache.set_company_news(cache_key, [item.model_dump() for item in news])
    return news


def get_market_cap(
    ticker: str,
    end_date: str,
    api_key: str = None,
) -> float | None:
    """Fetch market cap from yfinance company info."""
    _, stock = _resolve_ticker_with_history(ticker)
    info = _safe_stock_info(stock)
    market_cap = _safe_float(info.get("marketCap"))
    if market_cap is not None:
        return market_cap
    financial_metrics = get_financial_metrics(ticker, end_date, api_key=api_key)
    if not financial_metrics:
        return None
    return financial_metrics[0].market_cap


def prices_to_df(prices: list[Price]) -> pd.DataFrame:
    """Convert prices to a DataFrame."""
    if not prices:
        return pd.DataFrame(columns=["open", "close", "high", "low", "volume"])
    df = pd.DataFrame([p.model_dump() for p in prices])
    df["Date"] = pd.to_datetime(df["time"])
    df.set_index("Date", inplace=True)
    numeric_cols = ["open", "close", "high", "low", "volume"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.sort_index(inplace=True)
    return df


def get_price_data(ticker: str, start_date: str, end_date: str, api_key: str = None) -> pd.DataFrame:
    prices = get_prices(ticker, start_date, end_date, api_key=api_key)
    return prices_to_df(prices)
