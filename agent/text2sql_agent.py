"""
Strands Text-to-SQL Agent for Feature Store
============================================
Generates SQL queries from natural language questions using the database schema.

Usage:
  cd feature-store-poc
  python agent/text2sql_agent.py -q "What is the churn risk for C007?"
  python agent/text2sql_agent.py --interactive
"""

import sys
from pathlib import Path

from strands import Agent, tool

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
import os

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import REGION, AGENT_MODEL

os.environ["AWS_DEFAULT_REGION"] = REGION
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "metadata" / "schema_prompt.txt"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@tool
def get_schema() -> str:
    """Get the database schema including table names, columns, types, descriptions, and relationships.

    Returns:
        str: The full schema context for the sagemaker_featurestore database.
    """
    if SCHEMA_PATH.exists():
        return SCHEMA_PATH.read_text()
    return "Schema file not found. Run metadata/assemble_metadata.py first."


# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a text-to-SQL agent for a fintech behavioral platform.
Your job is to convert natural language questions into SQL queries for Amazon Athena.

You have access to this tool:
- get_schema: Get the full database schema (tables, columns, types, descriptions, relationships)

WORKFLOW:
1. When asked a data question, call get_schema to understand the tables and columns.
2. Generate a SQL query based on the schema and the user's question.
3. Return ONLY the raw SQL query as your final message.

CRITICAL RULES:
- Your final response must be ONLY the SQL query — no explanation, no markdown, no code fences, no semicolons.
- Always use the exact Glue table names from the schema (they are long names with numeric suffixes).
- Do NOT reference columns: write_time, api_invocation_time, is_deleted, event_time.
- Use Athena SQL syntax. Use DOUBLE not FLOAT for casts.
- Do NOT wrap SQL in ```sql``` blocks. Do NOT add any text before or after the SQL.
"""


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
def create_agent():
    return Agent(
        system_prompt=SYSTEM_PROMPT,
        tools=[get_schema],
        model=AGENT_MODEL,
    )


def generate_sql(question: str) -> str:
    """Run the agent and return clean SQL ready for execution."""
    import re

    agent = create_agent()
    response = agent(question)
    raw = str(response).strip()

    # Extract SQL: find the SELECT statement regardless of surrounding text
    sql = raw

    # If wrapped in markdown fences, extract from them
    if "```" in sql:
        parts = sql.split("```")
        for part in parts:
            cleaned = part.strip().removeprefix("sql").strip()
            if cleaned.upper().startswith("SELECT"):
                sql = cleaned
                break

    # If there's text before SELECT, extract from SELECT onward
    if not sql.upper().startswith("SELECT"):
        match = re.search(r"(SELECT\s+.+)", sql, re.IGNORECASE | re.DOTALL)
        if match:
            sql = match.group(1)

    # Strip semicolons (Athena doesn't accept them)
    sql = sql.rstrip(";").strip()
    return sql


if __name__ == "__main__":
    agent = create_agent()
    agent("Which customers have the highest churn risk?")
