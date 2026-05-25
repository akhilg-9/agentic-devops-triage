"""V2: Planning agent for DevOps incident triage.

Composes V1 routing with BM25 runbook retrieval to generate a structured response plan.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Optional

from openai import OpenAI

from .config import PromptConfig, load_prompt_config
from .retrieval import RetrievalHit, RunbookIndex
from .router import IncidentCategory, RouterAgent


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
        prompt_config: Optional[PromptConfig] = None,
        prompt_version: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.router = router
        self.index = index
        self.prompt_config = prompt_config or load_prompt_config()
        if prompt_version in {"baseline", "improved"}:
            self.prompt_config.planner.prompt_version = prompt_version  # type: ignore[assignment]
        self.prompt_version = self.prompt_config.planner.prompt_version
        self.client = client or OpenAI()
        self.model = model or self.prompt_config.planner_model()
        self.system_prompt = self.prompt_config.planner.system
        self.top_k = self.prompt_config.retrieval.top_k

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
            temperature=self.prompt_config.model.temperature,
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
