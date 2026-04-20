# Copilot Instructions for `ai-hedge-fund-tw`

## Build, test, and lint commands

### Python (repo root)
```bash
poetry install
poetry run pytest
poetry run pytest tests/test_cache.py
poetry run pytest tests/backtesting/test_execution.py::test_trade_executor_routes_actions
poetry run black .
poetry run isort .
poetry run flake8
```

### Frontend (`app/frontend`)
```bash
npm install
npm run dev
npm run build
npm run lint
```

### Backend (web API)
```bash
# from repo root
poetry run uvicorn app.backend.main:app --reload

# equivalent from app/backend
poetry run uvicorn main:app --reload
```

## High-level architecture

- The core trading workflow is a LangGraph `StateGraph` over `AgentState` (`src/main.py`, `src/graph/state.py`): `start_node -> selected analysts -> risk_management_agent -> portfolio_manager -> END`.
- Analyst registration is centralized in `src/utils/analysts.py` (`ANALYST_CONFIG`), and both CLI and web layers derive available analysts from this registry.
- The CLI path (`src/main.py`, `src/backtesting/cli.py`) and web path (`app/backend/routes/hedge_fund.py`, `app/backend/services/graph.py`) share agent functions and state shape; the web backend builds the graph dynamically from React Flow nodes/edges.
- Web runs/backtests stream status and results via SSE (`start`, `progress`, `complete`, `error`) from backend event models (`app/backend/models/events.py`) to frontend stream parsing (`app/frontend/src/services/api.ts`).
- The frontend creates unique node IDs by appending a 6-char suffix (e.g. `warren_buffett_abc123`) in `app/frontend/src/data/node-mappings.ts`; backend strips that suffix (`extract_base_agent_key`) to resolve real agent keys.
- `v2/` is a separate WIP quantitative pipeline and is explicitly not integrated into the main app yet (`v2/README.md`).

## Key conventions in this repository

- Agent functions follow `def <agent>(state: AgentState, agent_id: str = "...")` so they can run in both fixed CLI graphs and dynamically-instantiated web graphs with unique node IDs.
- Agents communicate through `AgentState` keys: `messages`, `data`, `metadata` (`src/graph/state.py`). In practice, analyst outputs are stored in `state["data"]["analyst_signals"][agent_id]`.
- Portfolio manager output is a JSON message on the final `HumanMessage` content, and downstream parsing assumes this shape (`src/agents/portfolio_manager.py`, `src/main.py`, `app/backend/services/graph.py`).
- Progress reporting uses the global `progress` tracker (`src/utils/progress.py`); backend endpoints register/unregister handlers around execution to convert updates into SSE events.
- Python formatting conventions are non-default: Black line length is `420`, and isort uses Black profile with alphabetical sorting (`pyproject.toml`).
- API keys can come from request payload or DB-backed stored keys in web mode (`app/backend/routes/hedge_fund.py`, `app/backend/services/api_key_service.py`), while CLI expects environment-based keys.
