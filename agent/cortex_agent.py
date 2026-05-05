"""
Mock Snowflake Cortex Agent
============================
Simulates a Snowflake Cortex Analyst agent that queries a Snowflake data warehouse.
In production, this would call the Cortex Analyst REST API.
For the POC, it returns mock responses based on the question.

The mock simulates Cortex's capabilities:
  - Natural language to SQL on Snowflake tables
  - Semantic model awareness (warehouse tables, dimensions, metrics)
  - Snowflake-native data (raw transactional data, aggregated views)

Usage:
  This agent is used as a tool by the orchestrator agent.
  It can also be run standalone for testing:

  python agent/cortex_agent.py -q "What is the total revenue by product category?"
"""

import sys
import json
from pathlib import Path
from strands import Agent, tool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import AGENT_MODEL

# ---------------------------------------------------------------------------
# Mock Snowflake data (simulates what Cortex would query)
# ---------------------------------------------------------------------------
SNOWFLAKE_TABLES = {
    "raw_transactions": {
        "description": "Raw credit card transaction data from Snowflake warehouse",
        "columns": ["transaction_id", "customer_id", "merchant_name", "category",
                     "amount", "transaction_date", "is_fraud", "channel"],
    },
    "customer_profiles": {
        "description": "Customer demographic and account data from Snowflake",
        "columns": ["customer_id", "name", "email", "signup_date", "plan_type",
                     "region", "age_group", "income_bracket"],
    },
    "monthly_aggregates": {
        "description": "Pre-computed monthly spend aggregates in Snowflake",
        "columns": ["customer_id", "month", "total_spend", "transaction_count",
                     "avg_transaction", "top_category", "fraud_flag_count"],
    },
}

# Mock query results keyed by question patterns
MOCK_RESPONSES = {
    "revenue": {
        "sql": "SELECT category, SUM(amount) AS total_revenue FROM raw_transactions GROUP BY category ORDER BY total_revenue DESC",
        "results": [
            {"category": "groceries", "total_revenue": 45200.00},
            {"category": "dining", "total_revenue": 32100.00},
            {"category": "travel", "total_revenue": 28500.00},
            {"category": "entertainment", "total_revenue": 15800.00},
            {"category": "utilities", "total_revenue": 12300.00},
        ],
        "interpretation": "Groceries leads spending at $45.2K, followed by dining at $32.1K and travel at $28.5K.",
    },
    "fraud": {
        "sql": "SELECT customer_id, COUNT(*) AS fraud_count, SUM(amount) AS fraud_amount FROM raw_transactions WHERE is_fraud = TRUE GROUP BY customer_id ORDER BY fraud_amount DESC LIMIT 5",
        "results": [
            {"customer_id": "C004", "fraud_count": 3, "fraud_amount": 2450.00},
            {"customer_id": "C010", "fraud_count": 2, "fraud_amount": 1800.00},
            {"customer_id": "C002", "fraud_count": 2, "fraud_amount": 950.00},
        ],
        "interpretation": "C004 has the most fraud exposure at $2,450 across 3 flagged transactions.",
    },
    "customer": {
        "sql": "SELECT cp.customer_id, cp.name, cp.plan_type, cp.region, ma.total_spend, ma.transaction_count FROM customer_profiles cp JOIN monthly_aggregates ma ON cp.customer_id = ma.customer_id WHERE ma.month = '2026-03' ORDER BY ma.total_spend DESC",
        "results": [
            {"customer_id": "C007", "name": "Alice Chen", "plan_type": "premium", "region": "West", "total_spend": 3600.00, "transaction_count": 45},
            {"customer_id": "C003", "name": "Bob Martinez", "plan_type": "premium", "region": "East", "total_spend": 2520.00, "transaction_count": 38},
            {"customer_id": "C001", "name": "Carol Kim", "plan_type": "standard", "region": "West", "total_spend": 1506.00, "transaction_count": 22},
        ],
        "interpretation": "Top spenders are premium customers in the West region.",
    },
    "trend": {
        "sql": "SELECT month, SUM(total_spend) AS monthly_total, COUNT(DISTINCT customer_id) AS active_customers FROM monthly_aggregates GROUP BY month ORDER BY month",
        "results": [
            {"month": "2026-01", "monthly_total": 89500.00, "active_customers": 10},
            {"month": "2026-02", "monthly_total": 92300.00, "active_customers": 10},
            {"month": "2026-03", "monthly_total": 95100.00, "active_customers": 9},
        ],
        "interpretation": "Monthly spend is trending up (+6.3% over 3 months) but one customer dropped off in March.",
    },
    "default": {
        "sql": "SELECT * FROM customer_profiles LIMIT 10",
        "results": [
            {"customer_id": "C001", "name": "Carol Kim", "plan_type": "standard", "region": "West"},
            {"customer_id": "C002", "name": "Dan Lee", "plan_type": "basic", "region": "East"},
            {"customer_id": "C003", "name": "Bob Martinez", "plan_type": "premium", "region": "East"},
            {"customer_id": "C007", "name": "Alice Chen", "plan_type": "premium", "region": "West"},
            {"customer_id": "C010", "name": "Eve Johnson", "plan_type": "basic", "region": "Central"},
        ],
        "interpretation": "Showing customer profiles from Snowflake warehouse.",
    },
}


def _match_response(question: str) -> dict:
    """Match a question to a mock response based on keywords."""
    q = question.lower()
    if any(w in q for w in ["revenue", "spend", "category", "spending"]):
        return MOCK_RESPONSES["revenue"]
    elif any(w in q for w in ["fraud", "suspicious", "flagged"]):
        return MOCK_RESPONSES["fraud"]
    elif any(w in q for w in ["customer", "profile", "who", "top spender"]):
        return MOCK_RESPONSES["customer"]
    elif any(w in q for w in ["trend", "month", "over time", "growth"]):
        return MOCK_RESPONSES["trend"]
    return MOCK_RESPONSES["default"]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@tool
def get_snowflake_schema() -> str:
    """Get the Snowflake data warehouse schema including table names, columns, and descriptions.

    Returns:
        str: The Snowflake warehouse schema.
    """
    lines = ["SNOWFLAKE WAREHOUSE SCHEMA", "=" * 40, ""]
    for table, info in SNOWFLAKE_TABLES.items():
        lines.append(f"TABLE: {table}")
        lines.append(f"  Description: {info['description']}")
        lines.append(f"  Columns: {', '.join(info['columns'])}")
        lines.append("")
    lines.append("RELATIONSHIPS:")
    lines.append("  All tables join on customer_id")
    return "\n".join(lines)


@tool
def query_snowflake(question: str) -> str:
    """Query the Snowflake data warehouse using Cortex Analyst.
    This simulates the Snowflake Cortex Analyst REST API that converts
    natural language to SQL and executes it against the Snowflake warehouse.

    Args:
        question: Natural language question about the Snowflake data.

    Returns:
        str: The Snowflake SQL query, results, and interpretation.
    """
    response = _match_response(question)

    lines = [
        "CORTEX ANALYST RESPONSE",
        "=" * 40,
        "",
        f"Generated Snowflake SQL:",
        f"  {response['sql']}",
        "",
        f"Results ({len(response['results'])} rows):",
    ]

    # Format results as table
    if response["results"]:
        headers = list(response["results"][0].keys())
        lines.append("  " + " | ".join(f"{h:<20}" for h in headers))
        lines.append("  " + "-" * (22 * len(headers)))
        for row in response["results"]:
            lines.append("  " + " | ".join(f"{str(v):<20}" for v in row.values()))

    lines.append("")
    lines.append(f"Interpretation: {response['interpretation']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# System Prompt & Agent
# ---------------------------------------------------------------------------
CORTEX_SYSTEM_PROMPT = """You are a Snowflake Cortex Analyst agent for a fintech behavioral platform.
You query the Snowflake data warehouse which contains raw transactional data, customer profiles,
and pre-computed aggregates.

You have access to these tools:
- get_snowflake_schema: Get the Snowflake warehouse schema
- query_snowflake: Query Snowflake using Cortex Analyst (natural language to SQL)

WORKFLOW:
1. When asked a data question, first call get_snowflake_schema to understand available tables.
2. Call query_snowflake with the user's question to get Snowflake SQL and results.
3. ALWAYS show the generated SQL query.
4. Present the results and provide interpretation.

DATA SCOPE:
- Raw transaction data (individual purchases, fraud flags)
- Customer demographic profiles (name, region, plan type)
- Monthly spend aggregates and trends
- This data lives in Snowflake, NOT in AWS Feature Store.
"""


def create_cortex_agent():
    return Agent(
        system_prompt=CORTEX_SYSTEM_PROMPT,
        tools=[get_snowflake_schema, query_snowflake],
        model=AGENT_MODEL,
    )


if __name__ == "__main__":
    agent = create_cortex_agent()
    agent("What is the total revenue by spending category?")
