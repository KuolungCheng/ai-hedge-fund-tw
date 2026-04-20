"""Constants and utilities related to analysts configuration."""

from src.agents.mr_huang import fundamentals_analyst_agent
from src.agents.mr_discount import growth_analyst_agent
from src.agents.mr_hindsight import news_sentiment_agent
from src.agents.mr_wang import sentiment_analyst_agent
from src.agents.mr_cancer import technical_analyst_agent
from src.agents.mr_airforce import valuation_analyst_agent

# Define analyst configuration - single source of truth
ANALYST_CONFIG = {
    "airforce": {
        "display_name": "嘎偉",
        "description": "偏空風險與估值派",
        "investing_style": "偏向防守與估值收縮邏輯，重視下行風險與資金保全。",
        "agent_func": valuation_analyst_agent,
        "type": "analyst",
        "order": 0,
    },
    "discount": {
        "display_name": "折折",
        "description": "成長趨勢派",
        "investing_style": "重視成長加速與題材延續，聚焦高成長與動能延續性。",
        "agent_func": growth_analyst_agent,
        "type": "analyst",
        "order": 1,
    },
    "huang": {
        "display_name": "照哥",
        "description": "基本面體質派",
        "investing_style": "以獲利品質、財務體質、估值合理性做中期判斷。",
        "agent_func": fundamentals_analyst_agent,
        "type": "analyst",
        "order": 2,
    },
    "cancer": {
        "display_name": "骨癌",
        "description": "技術面節奏派",
        "investing_style": "以價格、量能、波動與技術結構掌握進出節奏。",
        "agent_func": technical_analyst_agent,
        "type": "analyst",
        "order": 3,
    },
    "wang": {
        "display_name": "腦王",
        "description": "情緒與籌碼派",
        "investing_style": "觀察市場情緒與內部人交易，偏好群眾反應與資金行為訊號。",
        "agent_func": sentiment_analyst_agent,
        "type": "analyst",
        "order": 4,
    },
    "hindsight": {
        "display_name": "老謝",
        "description": "敘事與新聞派",
        "investing_style": "重視新聞敘事、產業輪動與總體議題對股價的邊際影響。",
        "agent_func": news_sentiment_agent,
        "type": "analyst",
        "order": 5,
    },
}

# Derive ANALYST_ORDER from ANALYST_CONFIG for backwards compatibility
ANALYST_ORDER = [(config["display_name"], key) for key, config in sorted(ANALYST_CONFIG.items(), key=lambda x: x[1]["order"])]


def get_analyst_nodes():
    """Get the mapping of analyst keys to their (node_name, agent_func) tuples."""
    return {key: (f"{key}_agent", config["agent_func"]) for key, config in ANALYST_CONFIG.items()}


def get_agents_list():
    """Get the list of agents for API responses."""
    return [
        {
            "key": key,
            "display_name": config["display_name"],
            "description": config["description"],
            "investing_style": config["investing_style"],
            "order": config["order"],
        }
        for key, config in sorted(ANALYST_CONFIG.items(), key=lambda x: x[1]["order"])
    ]
