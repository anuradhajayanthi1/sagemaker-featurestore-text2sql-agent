"""
Orchestrator Agent Evaluation
==============================
Evaluates the orchestrator's ability to route questions to the correct sub-agent.

Two checks per test case:
  1. Routing Check (programmatic) — did it call the correct agent(s)?
  2. Response Quality (LLM judge) — is the answer helpful and complete?

Run:
  AWS_PROFILE=default python evaluation/strands_eval_orchestrator.py
"""

import os
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent"))

from config import REGION, JUDGE_MODEL

os.environ["AWS_DEFAULT_REGION"] = REGION
os.environ["AWS_REGION"] = REGION

from strands_evals import Case, Experiment
from strands_evals.evaluators import OutputEvaluator, Evaluator
from strands_evals.extractors import tools_use_extractor
from strands_evals.types import EvaluationData, EvaluationOutput
from orchestrator_agent import create_orchestrator

EVAL_DIR = Path(__file__).resolve().parent
TEST_CASES_FILE = EVAL_DIR / "orchestrator_test_cases.json"
RESULTS_FILE = EVAL_DIR / "orchestrator_eval_results.json"


# =============================================================================
# Test Cases
# =============================================================================

def load_test_cases() -> list[Case]:
    with open(TEST_CASES_FILE) as f:
        data = json.load(f)

    return [
        Case[str, str](
            name=tc["id"],
            input=tc["question"],
            expected_output=tc["expected_route"],
            metadata={"category": tc["category"], "difficulty": tc["metadata"]["difficulty"]},
        )
        for tc in data["test_cases"]
    ]


# =============================================================================
# Agent Runner
# =============================================================================

def run_orchestrator(case: Case) -> dict:
    """Run the orchestrator on a question and capture which agents were called."""
    orchestrator = create_orchestrator()
    response = orchestrator(case.input)

    trajectory = tools_use_extractor.extract_agent_tools_used_from_messages(orchestrator.messages)

    return {"output": str(response), "trajectory": trajectory}


# =============================================================================
# Evaluator: Routing Check (Programmatic)
# =============================================================================

class RoutingEvaluator(Evaluator[str, str]):
    """Check if the orchestrator called the correct sub-agent(s)."""

    def evaluate(self, case: EvaluationData[str, str]) -> list[EvaluationOutput]:
        expected = case.expected_output  # "text2sql_featurestore", "cortex_snowflake", or "both"
        trajectory = case.actual_trajectory or []

        agents_called = {
            t.get("name") for t in trajectory
            if t.get("name") in ("text2sql_featurestore", "cortex_snowflake")
        }

        if expected == "both":
            if len(agents_called) == 2:
                return [EvaluationOutput(score=1.0, test_pass=True,
                    reason=f"Correctly called both agents", label="pass")]
            elif len(agents_called) == 1:
                return [EvaluationOutput(score=0.5, test_pass=False,
                    reason=f"Only called {agents_called}, expected both", label="partial")]
            else:
                return [EvaluationOutput(score=0.0, test_pass=False,
                    reason=f"Called: {agents_called}", label="fail")]
        else:
            if expected in agents_called and len(agents_called) == 1:
                return [EvaluationOutput(score=1.0, test_pass=True,
                    reason=f"Correctly routed to {expected}", label="pass")]
            elif expected in agents_called:
                return [EvaluationOutput(score=0.7, test_pass=True,
                    reason=f"Correct agent called, plus extra: {agents_called}", label="pass")]
            else:
                return [EvaluationOutput(score=0.0, test_pass=False,
                    reason=f"Expected {expected}, got {agents_called}", label="fail")]


# =============================================================================
# Run Evaluation
# =============================================================================

def main():
    test_cases = load_test_cases()
    print(f"Running orchestrator evaluation: {len(test_cases)} test cases\n")

    routing_check = RoutingEvaluator()

    response_quality = OutputEvaluator(
        model=JUDGE_MODEL,
        rubric="""
        Evaluate the orchestrator's response to a data question.

        Score 1.0: directly answers with specific data, mentions data source used
        Score 0.5: partially answers but missing details or unclear source
        Score 0.0: doesn't answer, errors, or irrelevant
        """,
        include_inputs=True,
    )

    experiment = Experiment[str, str](
        cases=test_cases,
        evaluators=[routing_check, response_quality],
    )
    reports = experiment.run_evaluations(run_orchestrator)

    # Print results
    names = ["Routing Check (Programmatic)", "Response Quality (LLM)"]
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
                {"score": report.scores[j], "pass": report.test_passes[j], "reason": report.reasons[j]}
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
