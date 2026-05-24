"""V2: Planning agent for DevOps incident triage.

Composes V1 routing with BM25 runbook retrieval to generate a structured response plan.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import List, Optional

from openai import OpenAI

from .retrieval import RetrievalHit, RunbookIndex
from .router import IncidentCategory, RouterAgent


SYSTEM_PROMPT_V2_BASELINE = """You are a DevOps incident planner. Given an alert and a set of candidate runbooks, produce a step-by-step response plan as JSON.

Output schema:
{
  "category": "<infra | app | security | data>",
  "primary_runbook": "<runbook_id of the best-matching runbook, or null if none apply>",
  "steps": [
    {"step": "<imperative action>", "why": "<one sentence>"}
  ]
}

Output nothing else."""


SYSTEM_PROMPT_V2_IMPROVED = """You are a senior on-call engineer producing a response plan for an incoming incident.

You receive:
1. The alert text.
2. The category that V1 routing assigned (treat as a strong prior, not absolute).
3. The top-K candidate runbooks retrieved by BM25, each with its id, title, and full body.

Your job:
- Pick the single most applicable runbook. If none truly apply, set "primary_runbook" to null and write generic-but-safe steps.
- Produce 3 to 7 concrete, ordered steps. Each step must be:
  * imperative ("Verify ...", "Roll back ...", "Open ..."),
  * specific enough that another engineer could execute it without asking follow-up questions,
  * grounded in the chosen runbook when possible — do not invent procedures the runbook does not describe.
- For each step, include a short "why" so the on-call understands intent.
- Order steps so that triage / read-only confirmation comes before mitigation, and mitigation before validation.
- Do not include post-incident review steps unless the alert is already mitigated.

Output schema:
{
  "category": "<infra | app | security | data>",
  "primary_runbook": "<runbook_id or null>",
  "steps": [
    {"step": "<imperative action>", "why": "<one sentence>"}
  ]
}

Output compact JSON only — no prose, no markdown."""


@dataclass
class PlanStep:
    step: str
    why: str


@dataclass
class IncidentPlan:
    category: IncidentCategory
    primary_runbook: Optional[str]
    steps: List[PlanStep]
    retrieval_hits: List[RetrievalHit] = field(default_factory=list)
    raw: Optional[str] = None


class PlannerAgent:
    def __init__(
        self,
        router: RouterAgent,
        index: RunbookIndex,
        client: Optional[OpenAI] = None,
        model: Optional[str] = None,
        prompt_version: str = "improved",
        top_k: int = 3,
    ):
        self.router = router
        self.index = index
        self.client = client or OpenAI()
        self.model = model or os.environ.get("PLANNER_MODEL", "gpt-4o-mini")
        if prompt_version == "baseline":
            self.system_prompt = SYSTEM_PROMPT_V2_BASELINE
        elif prompt_version == "improved":
            self.system_prompt = SYSTEM_PROMPT_V2_IMPROVED
        else:
            raise ValueError(f"unknown prompt_version: {prompt_version}")
        self.prompt_version = prompt_version
        self.top_k = top_k

    def _format_candidates(self, hits: List[RetrievalHit]) -> str:
        lines = []
        for i, hit in enumerate(hits, 1):
            lines.append(
                f"--- Candidate {i} ---\n"
                f"id: {hit.runbook.runbook_id}\n"
                f"title: {hit.runbook.title}\n"
                f"category: {hit.runbook.category}\n"
                f"bm25_score: {hit.score:.2f}\n"
                f"body:\n{hit.runbook.text}\n"
            )
        return "\n".join(lines)

    def plan(self, alert_text: str) -> IncidentPlan:
        routed = self.router.route(alert_text)
        hits = self.index.search(alert_text, k=self.top_k)

        user_content = (
            f"ALERT:\n{alert_text}\n\n"
            f"ROUTED_CATEGORY: {routed.category.value}\n\n"
            f"CANDIDATE_RUNBOOKS (top {self.top_k} by BM25):\n{self._format_candidates(hits)}"
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or ""

        try:
            parsed = json.loads(raw)
            category_str = str(parsed.get("category", "")).strip().lower()
            category = (
                IncidentCategory(category_str)
                if category_str in {c.value for c in IncidentCategory}
                else routed.category
            )
            primary_runbook = parsed.get("primary_runbook")
            if primary_runbook in {"", "null", "None"}:
                primary_runbook = None
            steps = [
                PlanStep(step=str(s.get("step", "")), why=str(s.get("why", "")))
                for s in parsed.get("steps", [])
                if isinstance(s, dict)
            ]
        except json.JSONDecodeError:
            category = routed.category
            primary_runbook = None
            steps = []

        return IncidentPlan(
            category=category,
            primary_runbook=primary_runbook,
            steps=steps,
            retrieval_hits=hits,
            raw=raw,
        )
