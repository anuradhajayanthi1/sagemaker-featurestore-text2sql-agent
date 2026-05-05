"""
Orchestrator Agent
==================
Multi-agent orchestrator that routes questions to the appropriate specialist:
  - AWS Text-to-SQL Agent: queries SageMaker Feature Store (Iceberg/Athena)
    for ML features, churn risk, engagement scores, predictive attributes
  - Snowflake Cortex Agent: queries Snowflake warehouse (mock)
    for raw transactions, customer profiles, spend aggregates, fraud data

The orchestrator decides which agent to call based on the question,
and can combine results from both when needed.

Architecture:
  User → Orchestrator → Text-to-SQL Agent (AWS Feature Store)
                      → Cortex Agent (Snowflake)

Usage:
  cd feature-store-poc
  python agent/orchestrator_agent.py -q "Compare churn risk with spending trends"
  python agent/orchestrator_agent.py --interactive
"""

import os
import sys
from pathlib import Path

# Force default AWS profile
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

from strands import Agent

# Import the sub-agents and config
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import AGENT_MODEL
from text2sql_agent import create_agent as create_text2sql_featurestore_agent
from cortex_agent import create_cortex_agent as create_cortex_snowflake_agent


# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------
ORCHESTRATOR_PROMPT = """You are the Data Intelligence Orchestrator.
You coordinate between two specialized data agents to answer questions about customers.

AVAILABLE AGENTS:

1. text2sql_featurestore — Queries AWS SageMaker Feature Store via Athena (Iceberg tables)
   USE FOR: ML features, churn risk scores, engagement scores, predictive attributes,
   customer segmentation, retention analysis, NPS scores, behavioral interaction history,
   nudge effectiveness, session data, credit utilization, payment patterns.
   DATA: 4 feature groups with ~40 ML-engineered features per customer.

2. cortex_snowflake — Queries Snowflake data warehouse via Cortex Analyst
   USE FOR: Raw transaction data, spending by category, fraud detection,
   customer demographic profiles (name, region, plan type), monthly spend aggregates,
   revenue trends over time, transaction counts.
   DATA: Raw transactional tables, customer profiles, monthly aggregates.

ROUTING RULES:
- Questions about ML scores, predictions, risk, engagement, retention → text2sql_featurestore
- Questions about transactions, revenue, fraud, demographics, spend trends → cortex_snowflake
- Questions that need BOTH (e.g., "compare churn risk with spending") → call BOTH agents
- When calling both, synthesize the results into a unified answer

RESPONSE FORMAT:
- Always indicate which agent(s) you used
- Show the SQL queries from each agent
- Provide a combined interpretation when using both agents
"""


# ---------------------------------------------------------------------------
# Create agents
# ---------------------------------------------------------------------------
def create_orchestrator():
    text2sql_featurestore = create_text2sql_featurestore_agent()
    cortex_snowflake = create_cortex_snowflake_agent()

    orchestrator = Agent(
        system_prompt=ORCHESTRATOR_PROMPT,
        tools=[
            text2sql_featurestore.as_tool(
                name="text2sql_featurestore",
                description="Text-to-SQL agent for AWS SageMaker Feature Store. Converts natural language to Athena SQL and queries ML features: churn risk, engagement scores, predictive attributes, retention, NPS, behavioral data, credit utilization, payment patterns.",
            ),
            cortex_snowflake.as_tool(
                name="cortex_snowflake",
                description="Snowflake Cortex Analyst agent. Queries Snowflake data warehouse for raw transactions, spending by category, fraud detection, customer demographics, monthly spend aggregates, and revenue trends.",
            ),
        ],
        model=AGENT_MODEL,
    )
    return orchestrator


if __name__ == "__main__":
    orchestrator = create_orchestrator()
    orchestrator("For customers with high churn risk, what are their spending patterns by category?")
