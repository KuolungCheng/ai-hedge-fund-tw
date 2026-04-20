# Gemini Project Context: AI Hedge Fund

This project is a proof of concept for an AI-powered hedge fund, designed for **educational and research purposes**. It utilizes a multi-agent system to simulate trading decisions based on various investing philosophies.

## Project Overview

The AI Hedge Fund employs a sophisticated multi-agent architecture orchestrated by **LangGraph**. A collection of "Analyst Agents," each embodying a famous investor's philosophy (e.g., Warren Buffett, Michael Burry, Cathie Wood), analyzes market data. Their signals are processed by a **Risk Manager** and finally a **Portfolio Manager** who makes the ultimate trading decisions.

### Core Technologies
- **Language:** Python 3.11+
- **Agent Orchestration:** [LangChain](https://github.com/langchain-ai/langchain) & [LangGraph](https://github.com/langchain-ai/langgraph)
- **Dependency Management:** [Poetry](https://python-poetry.org/)
- **Backend:** [FastAPI](https://fastapi.tiangolo.com/), SQLAlchemy, Alembic
- **Frontend:** React (TypeScript), [Vite](https://vitejs.dev/), Tailwind CSS, [Shadcn UI](https://ui.shadcn.com/), [XYFlow](https://reactflow.dev/) (for graph visualization)
- **Data Source:** [Financial Datasets API](https://financialdatasets.ai/)
- **LLM Support:** OpenAI, Anthropic, Groq, DeepSeek, and local models via **Ollama**

## Directory Structure

- `src/`: Core logic and agent implementations.
    - `src/agents/`: Individual agent logic (e.g., `warren_buffett.py`, `portfolio_manager.py`).
    - `src/graph/`: LangGraph state and workflow definitions.
    - `src/backtesting/`: Logic for the backtesting engine.
    - `src/tools/`: API integrations and data fetching tools.
- `app/`: Web application code.
    - `app/backend/`: FastAPI server, database models, and routes.
    - `app/frontend/`: React/Vite frontend.
- `v2/`: New architectural iterations (Pipeline execution, Feature engineering, etc.).
- `tests/`: Project test suite.
- `docker/`: Docker configuration for containerized deployment.

## Building and Running

### Prerequisites
- Python 3.11+
- Node.js & npm (for the web app)
- Poetry (`curl -sSL https://install.python-poetry.org | python3 -`)
- API Keys (OpenAI, Financial Datasets, etc.) configured in a `.env` file.

### Command Line Interface (CLI)
1.  **Install dependencies:**
    ```bash
    poetry install
    ```
2.  **Run the hedge fund:**
    ```bash
    poetry run python -m src.main --tickers AAPL,MSFT,NVDA
    ```
3.  **Run the backtester:**
    ```bash
    poetry run python -m src.backtester --tickers AAPL,MSFT,NVDA
    ```

### Web Application (Full-Stack)
The easiest way to run the full-stack app is using the provided scripts:
- **Mac/Linux:** `./run.sh`
- **Windows:** `run.bat`

#### Manual Developer Setup:
1.  **Backend:**
    ```bash
    cd app/backend
    poetry install
    poetry run uvicorn main:app --reload
    ```
2.  **Frontend:**
    ```bash
    cd app/frontend
    npm install
    npm run dev
    ```

## Development Conventions

- **Agent Architecture:** Agents are implemented as functions that take the `AgentState` and return an update to it. They are connected in a directed acyclic graph (DAG) via LangGraph.
- **State Management:** The `AgentState` (`src/graph/state.py`) is the single source of truth for the workflow, using `Annotated` and `operator.add` for message history.
- **Analyst Configuration:** `src/utils/analysts.py` is the central registry for all available analyst agents.
- **Formatting:** Python code follows `black` (line length 420) and `isort`.
- **Database:** Uses SQLAlchemy for ORM and Alembic for migrations (located in `app/backend/alembic`).
- **Testing:** Uses `pytest`. Run tests with `poetry run pytest`.

## Key Files for Reference
- `src/main.py`: CLI entry point and graph construction.
- `src/graph/state.py`: Definition of the shared agent state.
- `src/utils/analysts.py`: Configuration and registration of analysts.
- `app/backend/main.py`: FastAPI application entry point.
- `app/frontend/src/App.tsx`: Main frontend component.
- `pyproject.toml`: Project dependencies and metadata.
