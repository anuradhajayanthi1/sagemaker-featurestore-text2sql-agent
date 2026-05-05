# Text-to-SQL Feature Store Agents

A POC demonstrating text-to-SQL generation over SageMaker Feature Store using Strands Agents, with a multi-agent orchestrator and evaluation framework.

## Architecture

```
User Question
     │
     ▼
┌─────────────────────┐
│  Orchestrator Agent  │
└──────┬──────┬───────┘
       │      │
       ▼      ▼
┌──────────┐  ┌───────────────┐
│ text2sql │  │ cortex        │
│ feature  │  │ snowflake     │
│ store    │  │ (mock)        │
└────┬─────┘  └───────────────┘
     │
     ▼
┌──────────────────────────────┐
│ SageMaker Feature Store      │
│ (Iceberg / Athena)           │
└──────────────────────────────┘
```

## Components

| Directory | What it does |
|-----------|-------------|
| `agent/` | Strands agents — text2sql, cortex mock, orchestrator |
| `data/` | Sample CSV data (10 customers, ~40 features) |
| `metadata/` | Glue catalog tagging + schema assembler for LLM context |
| `evaluation/` | Strands Eval framework — LLM judge + Athena execution checks |
| `config.py` | Central config (region, models, bucket names) |

## Prerequisites

- Python 3.10+
- AWS account with SageMaker Feature Store, Athena, Glue, S3
- Bedrock model access (Claude Haiku 4.5 for agent, Claude Sonnet 4 for eval judge)
- AWS credentials configured in `~/.aws/credentials` under the `default` profile

## Setup

```bash
# Clone and install
cd feature-store-poc
pip install -r requirements.txt

# Set AWS profile
export AWS_PROFILE=default
export AWS_DEFAULT_REGION=us-east-1
```

## Step-by-Step: Full Setup from Scratch

### 1. Create Feature Store (one-time)

Create the IAM role, S3 bucket, and feature groups:

```bash
# Online-only feature groups (fast lookups)
python feature_store_online_poc.py

# Online + Offline with Iceberg (SQL queries via Athena)
python feature_store_online_offline_poc.py
```

This creates 4 feature groups in your AWS account with sample customer data.

### 2. Tag Metadata in Glue (one-time)

Add table descriptions, column comments, and join keys to the Glue Data Catalog:

```bash
python metadata/tag_glue_tables.py
```

### 3. Generate Schema Context (run when schema changes)

Auto-discover schema from Glue and generate the context file the agent uses:

```bash
python metadata/assemble_metadata.py --output schema
```

This creates `metadata/schema_prompt.txt` which the agent reads via the `get_schema` tool.

### 4. Test the Agent

```python
from agent.text2sql_agent import generate_sql

sql = generate_sql("Which customers have churn risk above 0.7?")
print(sql)
```

### 5. Run Evaluations

```bash
# Text-to-SQL agent (20 test cases)
python evaluation/strands_eval_text2sql.py

# Orchestrator agent (10 test cases)
python evaluation/strands_eval_orchestrator.py
```

Results are saved to `evaluation/text2sql_eval_results.json` and `evaluation/orchestrator_eval_results.json`.

### 6. Clean Up AWS Resources

```bash
# Delete feature groups (pass the timestamp suffix from creation)
python cleanup.py <suffix>
```

## Evaluation Results

### Text-to-SQL Agent
| Evaluator | Score | Pass Rate |
|-----------|-------|-----------|
| SQL Semantic Check (LLM Judge) | 0.88 | 16/20 |
| SQL Results Check (Athena) | 0.97 | 19/20 |

### Orchestrator Agent
| Evaluator | Score | Pass Rate |
|-----------|-------|-----------|
| Routing Check (Programmatic) | 1.00 | 10/10 |
| Response Quality (LLM Judge) | 0.68 | 5/10 |

## Configuration

All config is in `config.py`:
- `AGENT_MODEL` — model for SQL generation (default: Claude Haiku 4.5)
- `JUDGE_MODEL` — model for evaluation judging (default: Claude Sonnet 4)
- `REGION`, `DATABASE`, `ATHENA_OUTPUT` — AWS resource config (auto-detected from credentials)

## Project Structure

```
feature-store-poc/
├── agent/
│   ├── text2sql_agent.py          # SQL generation agent (Strands)
│   ├── cortex_agent.py            # Mock Snowflake Cortex agent
│   └── orchestrator_agent.py      # Multi-agent router
├── data/                          # Sample customer data (4 CSVs)
├── evaluation/
│   ├── strands_eval_text2sql.py   # Text-to-SQL evaluation
│   ├── strands_eval_orchestrator.py # Orchestrator evaluation
│   ├── text2sql_test_cases.json   # 20 test cases (simple → complex)
│   └── orchestrator_test_cases.json # 10 routing test cases
├── metadata/
│   ├── tag_glue_tables.py         # Enrich Glue catalog with descriptions
│   ├── assemble_metadata.py       # Auto-discover schema for LLM context
│   └── schema_prompt.txt          # Generated schema context
├── config.py                      # Central configuration
├── feature_store_online_poc.py    # Create online-only feature groups
├── feature_store_online_offline_poc.py # Create online+offline (Iceberg)
├── lookup_demo.py                 # Quick online store lookup
├── cleanup.py                     # Delete feature groups
└── requirements.txt
```
