"""V1: Router agent for DevOps incident triage.

Classifies an incoming alert into one of four categories: infra, app, security, data.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from openai import OpenAI

from .config import PromptConfig, load_prompt_config


class IncidentCategory(str, Enum):
    INFRA = "infra"
    APP = "app"
    SECURITY = "security"
    DATA = "data"
    UNKNOWN = "unknown"


CATEGORY_DEFINITIONS = {
    IncidentCategory.INFRA: (
        "Infrastructure: compute nodes, kubernetes, networking, DNS, storage volumes, "
        "load balancers, cloud-provider outages, primary database availability."
    ),
    IncidentCategory.APP: (
        "Application: code-level bugs, 5xx surges, latency regressions, deploy regressions, "
        "OOMKilled application pods, frontend errors, mobile crashes."
    ),
    IncidentCategory.SECURITY: (
        "Security: leaked credentials, suspicious logins, account takeover, vulnerabilities, "
        "abuse, pen-test findings, anomalous billing that suggests compromise."
    ),
    IncidentCategory.DATA: (
        "Data: ETL pipeline failures, dbt test failures, data freshness breaches, "
        "warehouse query queues, CDC replication lag, schema drift."
    ),
}


@dataclass
class RouterResult:
    category: IncidentCategory
    rationale: Optional[str] = None
    raw: Optional[str] = None


class RouterAgent:
    """V1 — single LLM classification call. Prompts come from prompts/v*.yaml."""

    def __init__(
        self,
        client: Optional[OpenAI] = None,
        prompt_config: Optional[PromptConfig] = None,
        prompt_version: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.prompt_config = prompt_config or load_prompt_config()
        # Allow back-compat A/B override: caller can pass "baseline" or "improved"
        # to swap which prompt body inside the same config version they're using.
        if prompt_version in {"baseline", "improved"}:
            self.prompt_config.router.prompt_version = prompt_version  # type: ignore[assignment]
        self.prompt_version = self.prompt_config.router.prompt_version
        self.client = client or OpenAI()
        self.model = model or self.prompt_config.router_model()
        self.system_prompt = self.prompt_config.router.system

    def route(self, alert_text: str) -> RouterResult:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": alert_text},
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
                else IncidentCategory.UNKNOWN
            )
            rationale = parsed.get("rationale")
        except (json.JSONDecodeError, ValueError):
            category = IncidentCategory.UNKNOWN
            rationale = None
        return RouterResult(category=category, rationale=rationale, raw=raw)
