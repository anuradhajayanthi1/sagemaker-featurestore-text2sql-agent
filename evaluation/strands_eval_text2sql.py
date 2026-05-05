"""
Text-to-SQL Agent Evaluation
=============================
Evaluates whether the agent generates correct SQL from natural language questions.

Two checks per test case:
  1. SQL Semantic Check (LLM judge) — is the generated SQL logically equivalent to ground truth?
  2. SQL Results Check (programmatic) — do both SQLs return the same data from Athena?

Run:
  cd feature-store-poc
  python evaluation/strands_eval_text2sql.py
"""

import os
import sys
import json
import time
from pathlib import Path
from decimal import Decimal

# Setup paths and config
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent"))

from config import REGION, DATABASE, ATHENA_OUTPUT, JUDGE_MODEL

os.environ["AWS_DEFAULT_REGION"] = REGION
os.environ["AWS_REGION"] = REGION

import boto3
import pandas as pd
from strands_evals import Case, Experiment
from strands_evals.evaluators import OutputEvaluator, Evaluator
from strands_evals.types import EvaluationData, EvaluationOutput
from text2sql_agent import generate_sql as agent_generate_sql

EVAL_DIR = Path(__file__).resolve().parent
TEST_CASES_FILE = EVAL_DIR / "text2sql_test_cases.json"
RESULTS_FILE = EVAL_DIR / "text2sql_eval_results.json"


# =============================================================================
# Test Cases
# =============================================================================

def load_test_cases() -> list[Case]:
    """Load questions and ground truth SQL from the test cases file."""
    with open(TEST_CASES_FILE) as f:
        data = json.load(f)

    return [
        Case[str, str](
            name=tc["id"],
            input=tc["question"],
            expected_output=tc["ground_truth_sql"],
            metadata={"level": tc["level"], "category": tc["category"]},
        )
        for tc in data["test_cases"]
    ]


# =============================================================================
# Agent Runner
# =============================================================================

def generate_sql(case: Case) -> dict:
    """Run the text-to-SQL agent on a question and return the generated SQL."""
    sql = agent_generate_sql(case.input)
    return {"output": sql}


# =============================================================================
# Evaluator: SQL Results Check (Programmatic)
# =============================================================================

class SQLResultsEvaluator(Evaluator[str, str]):
    """Execute both SQLs on Athena and compare the returned data."""

    def evaluate(self, case: EvaluationData[str, str]) -> list[EvaluationOutput]:
        ground_truth_sql = case.expected_output
        generated_sql = case.actual_output

        # Validate generated SQL
        if not generated_sql or "SELECT" not in generated_sql.upper():
            return [self._fail("Agent did not return a valid SELECT statement")]

        # Run both on Athena
        athena = boto3.client("athena", region_name=REGION)

        try:
            expected_df = self._run_query(athena, ground_truth_sql)
        except Exception as e:
            return [self._fail(f"Ground truth SQL error: {str(e)[:80]}")]

        try:
            actual_df = self._run_query(athena, generated_sql)
        except Exception as e:
            return [self._fail(f"Generated SQL error: {str(e)[:80]}")]

        # Compare row counts
        if len(expected_df) != len(actual_df):
            return [self._fail(
                f"Row count mismatch: expected {len(expected_df)}, got {len(actual_df)}"
            )]

        # Compare values on shared columns
        shared_cols = sorted(set(expected_df.columns) & set(actual_df.columns))
        if not shared_cols:
            # No shared column names — compare by position if same number of columns
            if len(expected_df.columns) == len(actual_df.columns):
                expected_sorted = expected_df.sort_values(by=list(expected_df.columns)).reset_index(drop=True)
                actual_sorted = actual_df.sort_values(by=list(actual_df.columns)).reset_index(drop=True)
                # Compare values ignoring column names
                expected_sorted.columns = range(len(expected_sorted.columns))
                actual_sorted.columns = range(len(actual_sorted.columns))
                if self._dataframes_match(expected_sorted, actual_sorted):
                    return [EvaluationOutput(
                        score=1.0, test_pass=True,
                        reason=f"Results match by position: {len(actual_df.columns)} columns, {len(actual_df)} rows (aliases differ)",
                        label="pass",
                    )]
                else:
                    return [self._partial(f"Same shape but values differ")]
            else:
                return [self._partial(
                    f"No shared columns and different column count: expected {list(expected_df.columns)}, got {list(actual_df.columns)}"
                )]

        expected_sorted = expected_df[shared_cols].sort_values(by=shared_cols).reset_index(drop=True)
        actual_sorted = actual_df[shared_cols].sort_values(by=shared_cols).reset_index(drop=True)

        if self._dataframes_match(expected_sorted, actual_sorted):
            return [EvaluationOutput(
                score=1.0, test_pass=True,
                reason=f"Results match: {len(shared_cols)} columns, {len(actual_df)} rows",
                label="pass",
            )]
        else:
            return [self._partial(f"Same shape but values differ on {shared_cols}")]

    # --- Helpers ---

    def _run_query(self, athena, sql: str) -> pd.DataFrame:
        resp = athena.start_query_execution(
            QueryString=sql,
            QueryExecutionContext={"Database": DATABASE},
            ResultConfiguration={"OutputLocation": ATHENA_OUTPUT},
        )
        qid = resp["QueryExecutionId"]

        for _ in range(60):
            status = athena.get_query_execution(QueryExecutionId=qid)
            state = status["QueryExecution"]["Status"]["State"]
            if state == "SUCCEEDED":
                break
            elif state in ("FAILED", "CANCELLED"):
                raise RuntimeError(status["QueryExecution"]["Status"].get("StateChangeReason", ""))
            time.sleep(1)
        else:
            raise TimeoutError("Athena query timed out")

        rows, cols = [], None
        for page in athena.get_paginator("get_query_results").paginate(QueryExecutionId=qid):
            if cols is None:
                cols = [c["Name"] for c in page["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]]
            for i, row in enumerate(page["ResultSet"]["Rows"]):
                if i == 0 and not rows:
                    continue
                rows.append([f.get("VarCharValue", "") for f in row["Data"]])

        df = pd.DataFrame(rows, columns=cols)
        for col in df.columns:
            try:
                df[col] = pd.to_numeric(df[col])
            except (ValueError, TypeError):
                pass
        return df

    def _dataframes_match(self, df1: pd.DataFrame, df2: pd.DataFrame) -> bool:
        if df1.shape != df2.shape:
            return False
        for i in range(df1.shape[0]):
            for j in range(df1.shape[1]):
                v1, v2 = df1.iloc[i, j], df2.iloc[i, j]
                if isinstance(v1, (float, Decimal)) and isinstance(v2, (float, Decimal)):
                    if abs(float(v1) - float(v2)) > 1e-4:
                        return False
                elif str(v1) != str(v2):
                    return False
        return True

    def _fail(self, reason: str) -> EvaluationOutput:
        return EvaluationOutput(score=0.0, test_pass=False, reason=reason, label="fail")

    def _partial(self, reason: str) -> EvaluationOutput:
        return EvaluationOutput(score=0.3, test_pass=False, reason=reason, label="partial")


# =============================================================================
# Run Evaluation
# =============================================================================

def main():
    test_cases = load_test_cases()
    print(f"Running text-to-SQL evaluation: {len(test_cases)} test cases\n")

    # Two evaluators
    sql_semantic_check = OutputEvaluator(
        model=JUDGE_MODEL,
        rubric="""
        Compare the actual SQL against the expected SQL.
        Both should return the same data when executed.

        Score 1.0: correct table(s), correct filters, equivalent results (extra columns OK)
        Score 0.5: correct table and filters, but significantly more columns than needed
        Score 0.0: wrong table, wrong filters, or fundamentally different logic
        """,
        include_inputs=True,
    )

    sql_results_check = SQLResultsEvaluator()

    # Run
    experiment = Experiment[str, str](
        cases=test_cases,
        evaluators=[sql_semantic_check, sql_results_check],
    )
    reports = experiment.run_evaluations(generate_sql)

    # Print results
    names = ["SQL Semantic Check (LLM)", "SQL Results Check (Athena)"]
    for i, report in enumerate(reports):
        total = len(report.scores)
        passed = sum(1 for p in report.test_passes if p)
        print(f"\n{'='*60}")
        print(f"{names[i]}: {passed}/{total} passed | avg score: {report.overall_score:.2f}")
        print(f"{'='*60}")
        for j, case_name in enumerate(report.cases):
            status = "✅" if report.test_passes[j] else "❌"
            reason = report.reasons[j][:80] if report.reasons[j] else ""
            print(f"  {status} score={report.scores[j]:.1f} | {reason}")

    # Save
    results = {
        names[i]: {
            "score": report.overall_score,
            "pass_rate": f"{sum(report.test_passes)}/{len(report.test_passes)}",
            "details": [
                {"case": str(report.cases[j]), "score": report.scores[j],
                 "pass": report.test_passes[j], "reason": report.reasons[j]}
                for j in range(len(report.scores))
            ],
        }
        for i, report in enumerate(reports)
    }
    with open(RESULTS_FILE, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
