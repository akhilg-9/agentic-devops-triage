"""Evaluation harness for the router and planner agents.

Implements the CC (continuous calibration) side of the CC/CD loop: metrics, per-category
breakdowns, retrieval recall, and an LLM-as-judge for plan quality.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import pandas as pd
from openai import OpenAI
from tqdm.auto import tqdm

from .planner import IncidentPlan, PlannerAgent
from .router import IncidentCategory, RouterAgent


@dataclass
class RouterEvalResult:
    accuracy: float
    per_category_accuracy: Dict[str, float]
    confusion: Dict[str, Dict[str, int]]
    predictions: pd.DataFrame


def evaluate_router(
    router: RouterAgent,
    test_cases: pd.DataFrame,
    progress: bool = True,
) -> RouterEvalResult:
    """Run the router over a test set and return accuracy + per-category breakdown.

    `test_cases` must have columns: id, alert_text, expected_category.
    """
    required = {"id", "alert_text", "expected_category"}
    missing = required - set(test_cases.columns)
    if missing:
        raise ValueError(f"test_cases missing required columns: {missing}")

    rows = []
    iterator = test_cases.itertuples(index=False)
    if progress:
        iterator = tqdm(iterator, total=len(test_cases), desc="router eval")

    for row in iterator:
        result = router.route(row.alert_text)
        rows.append(
            {
                "id": row.id,
                "alert_text": row.alert_text,
                "expected": row.expected_category,
                "predicted": result.category.value,
                "rationale": result.rationale,
                "correct": result.category.value == row.expected_category,
            }
        )

    predictions = pd.DataFrame(rows)
    accuracy = float(predictions["correct"].mean()) if len(predictions) else 0.0

    per_category = (
        predictions.groupby("expected")["correct"].mean().to_dict()
        if len(predictions)
        else {}
    )

    confusion: Dict[str, Dict[str, int]] = {}
    for _, r in predictions.iterrows():
        confusion.setdefault(r["expected"], {}).setdefault(r["predicted"], 0)
        confusion[r["expected"]][r["predicted"]] += 1

    return RouterEvalResult(
        accuracy=accuracy,
        per_category_accuracy={k: float(v) for k, v in per_category.items()},
        confusion=confusion,
        predictions=predictions,
    )


def retrieval_recall_at_k(plan: IncidentPlan, expected_runbook: str, k: Optional[int] = None) -> bool:
    """Was the expected runbook present in the top-K BM25 hits?"""
    hits = plan.retrieval_hits if k is None else plan.retrieval_hits[:k]
    return any(h.runbook.runbook_id == expected_runbook for h in hits)


JUDGE_SYSTEM_PROMPT = """You are a strict grader evaluating an automatically-generated incident-response plan against a ground-truth runbook.

Score the plan on three dimensions, each from 1 to 5:

1. groundedness — does the plan's steps follow procedures present in the runbook? Penalize invented steps.
2. completeness — does the plan cover the critical triage, mitigation, and validation steps the runbook prescribes?
3. actionability — is each step concrete enough for an on-call engineer to execute without follow-up questions?

Output JSON only:
{"groundedness": <1-5>, "completeness": <1-5>, "actionability": <1-5>, "notes": "<one sentence>"}"""


@dataclass
class PlanJudgement:
    groundedness: int
    completeness: int
    actionability: int
    notes: str
    raw: str


def judge_plan(
    plan: IncidentPlan,
    expected_runbook_text: str,
    client: Optional[OpenAI] = None,
    model: Optional[str] = None,
) -> PlanJudgement:
    client = client or OpenAI()
    model = model or os.environ.get("JUDGE_MODEL", "gpt-4o")

    plan_text = json.dumps(
        {
            "category": plan.category.value,
            "primary_runbook": plan.primary_runbook,
            "steps": [{"step": s.step, "why": s.why} for s in plan.steps],
        },
        indent=2,
    )

    user_content = (
        f"GROUND_TRUTH_RUNBOOK:\n{expected_runbook_text}\n\n"
        f"GENERATED_PLAN:\n{plan_text}"
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or ""
    try:
        parsed = json.loads(raw)
        return PlanJudgement(
            groundedness=int(parsed.get("groundedness", 0)),
            completeness=int(parsed.get("completeness", 0)),
            actionability=int(parsed.get("actionability", 0)),
            notes=str(parsed.get("notes", "")),
            raw=raw,
        )
    except (json.JSONDecodeError, ValueError, TypeError):
        return PlanJudgement(
            groundedness=0, completeness=0, actionability=0, notes="parse-failure", raw=raw
        )


@dataclass
class PlannerEvalResult:
    routing_accuracy: float
    recall_at_1: float
    recall_at_k: float
    refusal_accuracy: float
    avg_groundedness: float
    avg_completeness: float
    avg_actionability: float
    predictions: pd.DataFrame


def evaluate_planner(
    planner: PlannerAgent,
    test_cases: pd.DataFrame,
    judge: bool = True,
    judge_client: Optional[OpenAI] = None,
    judge_model: Optional[str] = None,
    progress: bool = True,
) -> PlannerEvalResult:
    """Run the planner over a test set.

    `test_cases` must have columns: id, alert_text, expected_category, expected_runbook.
    """
    required = {"id", "alert_text", "expected_category", "expected_runbook"}
    missing = required - set(test_cases.columns)
    if missing:
        raise ValueError(f"test_cases missing required columns: {missing}")

    runbook_by_id = {rb.runbook_id: rb for rb in planner.index.runbooks}

    rows = []
    iterator = test_cases.itertuples(index=False)
    if progress:
        iterator = tqdm(iterator, total=len(test_cases), desc="planner eval")

    for row in iterator:
        plan = planner.plan(row.alert_text)

        expected_runbook = (str(row.expected_runbook) if row.expected_runbook is not None else "").strip()
        if expected_runbook.lower() in {"", "nan", "none"}:
            expected_runbook = ""
        is_refusal = expected_runbook == ""

        if is_refusal:
            in_top_1 = None
            in_top_k = None
            # "Correct refusal" = planner correctly returned a null primary_runbook.
            refusal_correct = plan.primary_runbook is None
        else:
            in_top_1 = retrieval_recall_at_k(plan, expected_runbook, k=1)
            in_top_k = retrieval_recall_at_k(plan, expected_runbook)
            refusal_correct = None
        category_correct = plan.category.value == row.expected_category

        judgement = None
        if judge and not is_refusal:
            expected_text = runbook_by_id.get(expected_runbook)
            if expected_text is not None:
                judgement = judge_plan(
                    plan,
                    expected_runbook_text=expected_text.text,
                    client=judge_client,
                    model=judge_model,
                )

        rows.append(
            {
                "id": row.id,
                "alert_text": row.alert_text,
                "expected_category": row.expected_category,
                "predicted_category": plan.category.value,
                "category_correct": category_correct,
                "expected_runbook": expected_runbook,
                "primary_runbook": plan.primary_runbook,
                "is_refusal": is_refusal,
                "refusal_correct": refusal_correct,
                "in_top_1": in_top_1,
                "in_top_k": in_top_k,
                "num_steps": len(plan.steps),
                "groundedness": judgement.groundedness if judgement else None,
                "completeness": judgement.completeness if judgement else None,
                "actionability": judgement.actionability if judgement else None,
                "judge_notes": judgement.notes if judgement else None,
            }
        )

    predictions = pd.DataFrame(rows)

    routing_accuracy = float(predictions["category_correct"].mean()) if len(predictions) else 0.0
    non_refusal = predictions[~predictions["is_refusal"]] if len(predictions) else predictions
    recall_at_1 = float(non_refusal["in_top_1"].mean()) if len(non_refusal) else 0.0
    recall_at_k = float(non_refusal["in_top_k"].mean()) if len(non_refusal) else 0.0
    refusal_rows = predictions[predictions["is_refusal"]] if len(predictions) else predictions
    refusal_accuracy = float(refusal_rows["refusal_correct"].mean()) if len(refusal_rows) else 0.0

    if judge and "groundedness" in predictions and predictions["groundedness"].notna().any():
        avg_grounded = float(predictions["groundedness"].dropna().mean())
        avg_complete = float(predictions["completeness"].dropna().mean())
        avg_action = float(predictions["actionability"].dropna().mean())
    else:
        avg_grounded = avg_complete = avg_action = 0.0

    return PlannerEvalResult(
        routing_accuracy=routing_accuracy,
        recall_at_1=recall_at_1,
        recall_at_k=recall_at_k,
        refusal_accuracy=refusal_accuracy,
        avg_groundedness=avg_grounded,
        avg_completeness=avg_complete,
        avg_actionability=avg_action,
        predictions=predictions,
    )
