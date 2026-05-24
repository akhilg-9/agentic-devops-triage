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


SYSTEM_PROMPT_V1_BASELINE = """You are a DevOps incident router. You receive a single alert and respond with the single most appropriate category.

Categories:
- infra
- app
- security
- data

Respond as JSON with one key, "category", whose value is one of the four strings above. Output nothing else."""


SYSTEM_PROMPT_V1_IMPROVED = """You are a senior on-call engineer triaging an incoming alert. You classify each alert into exactly one of four categories.

Category definitions:
- infra: compute nodes, kubernetes, networking/DNS, storage volumes, load balancers, cloud-provider outages, primary database availability problems (the DB itself is down, not its data).
- app: code-level bugs, HTTP 5xx surges, latency regressions, deploy regressions, application-pod OOMKilled, frontend / mobile crashes.
- security: leaked credentials, suspicious or impossible-travel logins, account takeover, CVEs, abuse, pen-test findings, anomalous spend suggesting compromise.
- data: ETL / DAG failures, dbt test failures, data freshness SLA breaches, warehouse query queues, CDC replication lag, schema drift.

Disambiguation rules — apply in order:
1. If the alert mentions credentials, secrets, suspicious auth, or abuse → security.
2. If the alert is about data correctness, freshness, dbt, ETL, CDC, warehouse → data, even if it manifests on infrastructure.
3. If the database server itself is unreachable / down → infra. If the *data inside* the database is wrong or stale → data.
4. If the alert is an HTTP-layer symptom (5xx, p99) without an underlying infra cause → app.
5. Otherwise → infra.

Respond as compact JSON: {"category": "<one of: infra, app, security, data>", "rationale": "<one short sentence>"}. Output nothing else."""


@dataclass
class RouterResult:
    category: IncidentCategory
    rationale: Optional[str] = None
    raw: Optional[str] = None


class RouterAgent:
    def __init__(
        self,
        client: Optional[OpenAI] = None,
        model: Optional[str] = None,
        prompt_version: str = "improved",
    ):
        self.client = client or OpenAI()
        self.model = model or os.environ.get("ROUTER_MODEL", "gpt-4o-mini")
        if prompt_version == "baseline":
            self.system_prompt = SYSTEM_PROMPT_V1_BASELINE
        elif prompt_version == "improved":
            self.system_prompt = SYSTEM_PROMPT_V1_IMPROVED
        else:
            raise ValueError(f"unknown prompt_version: {prompt_version}")
        self.prompt_version = prompt_version

    def route(self, alert_text: str) -> RouterResult:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": alert_text},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or ""
        try:
            parsed = json.loads(raw)
            category_str = str(parsed.get("category", "")).strip().lower()
            category = IncidentCategory(category_str) if category_str in {
                c.value for c in IncidentCategory
            } else IncidentCategory.UNKNOWN
            rationale = parsed.get("rationale")
        except (json.JSONDecodeError, ValueError):
            category = IncidentCategory.UNKNOWN
            rationale = None
        return RouterResult(category=category, rationale=rationale, raw=raw)
