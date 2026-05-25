"""Mock DevOps tools for the V3 ReAct agent.

These tools simulate the kinds of read-only investigations an on-call engineer
would perform during triage: pull recent deploys, sample logs, check pod state,
read a metric, search the runbook library, and finally propose a plan.

Returns deterministic-but-realistic mock data so the agent has to reason over
real-looking signals without touching any production system.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .retrieval import RunbookIndex


# ---------------------------------------------------------------------------
# Mocked environment
# ---------------------------------------------------------------------------


def _seeded_rng(*parts: str) -> random.Random:
    """Returns a Random seeded by the concatenated string parts. Deterministic."""
    key = "|".join(parts).encode()
    seed = int(hashlib.sha256(key).hexdigest()[:16], 16)
    return random.Random(seed)


@dataclass
class Deploy:
    service: str
    sha: str
    deployed_minutes_ago: int
    author: str


@dataclass
class LogLine:
    timestamp_minutes_ago: int
    severity: str
    message: str


@dataclass
class PodStatus:
    deployment: str
    desired_replicas: int
    ready_replicas: int
    restarts_last_hour: int
    last_restart_reason: Optional[str]


@dataclass
class MetricReading:
    metric: str
    service: str
    current_value: float
    baseline_value: float
    unit: str
    window_minutes: int


class MockDevOpsEnv:
    """A deterministic, in-memory mock of an SRE environment.

    Tools query this object. The same (service, alert_signature) pair always
    returns the same data, so notebook runs are reproducible.
    """

    def __init__(self, alert_signature: str):
        self.alert_signature = alert_signature

    # ---------------- tools ----------------

    def get_recent_deploys(self, service: str, window_minutes: int = 60) -> List[Dict[str, Any]]:
        rng = _seeded_rng(self.alert_signature, "deploys", service, str(window_minutes))
        # ~40% chance there was a deploy in the window; if so, 1-2 of them
        if rng.random() > 0.4:
            return []
        n = rng.choice([1, 1, 2])
        deploys = []
        for _ in range(n):
            minutes_ago = rng.randint(1, max(2, window_minutes - 1))
            deploys.append(
                Deploy(
                    service=service,
                    sha=rng.choice("abcdef0123456789") * 7,
                    deployed_minutes_ago=minutes_ago,
                    author=rng.choice(["maya@corp", "leo@corp", "priya@corp", "sam@corp"]),
                )
            )
        return [asdict(d) for d in sorted(deploys, key=lambda d: d.deployed_minutes_ago)]

    def query_logs(self, service: str, severity: str = "error", limit: int = 5) -> List[Dict[str, Any]]:
        rng = _seeded_rng(self.alert_signature, "logs", service, severity)
        templates = {
            "error": [
                "NullPointerException at com.acme.{svc}.PaymentResolver.resolve(line 142)",
                "psycopg2.OperationalError: connection to server at \"prod-postgres-1\" failed",
                "context deadline exceeded calling upstream {svc}-api",
                "redis: connection pool exhausted (size=64, in_use=64)",
                "OOM-killed: container {svc}-worker exceeded memory limit 512Mi",
                "TimeoutError after 30000ms calling /v2/payments",
            ],
            "warn": [
                "slow query detected: 2400ms on table user_events",
                "circuit breaker half-open for downstream notify-svc",
                "retrying request to inventory-svc (attempt 3/5)",
                "cache miss rate climbed above 40% in the last 5m",
            ],
            "info": [
                "graceful shutdown initiated for pod {svc}-7d4f8c-x9k2j",
                "rolling update completed, 12/12 pods ready",
            ],
        }
        pool = templates.get(severity, templates["error"])
        lines = []
        for _ in range(min(limit, len(pool))):
            msg = rng.choice(pool).replace("{svc}", service)
            lines.append(
                LogLine(
                    timestamp_minutes_ago=rng.randint(0, 25),
                    severity=severity,
                    message=msg,
                )
            )
        lines.sort(key=lambda x: x.timestamp_minutes_ago)
        return [asdict(line) for line in lines]

    def check_pod_status(self, deployment: str) -> Dict[str, Any]:
        rng = _seeded_rng(self.alert_signature, "pods", deployment)
        desired = rng.choice([6, 8, 10, 12])
        # ~30% chance of unhealthy state
        unhealthy = rng.random() < 0.35
        ready = desired - (rng.randint(1, max(1, desired // 3)) if unhealthy else 0)
        restarts = rng.randint(8, 40) if unhealthy else rng.randint(0, 2)
        reasons = ["OOMKilled", "CrashLoopBackOff", "ImagePullBackOff", "Error"]
        last_reason = rng.choice(reasons) if unhealthy else None
        status = PodStatus(
            deployment=deployment,
            desired_replicas=desired,
            ready_replicas=ready,
            restarts_last_hour=restarts,
            last_restart_reason=last_reason,
        )
        return asdict(status)

    def get_metric(
        self,
        metric: str,
        service: str,
        window_minutes: int = 15,
    ) -> Dict[str, Any]:
        rng = _seeded_rng(self.alert_signature, "metric", metric, service)
        if "latency" in metric.lower() or "p99" in metric.lower():
            baseline = round(rng.uniform(120, 240), 1)
            current = round(baseline * rng.uniform(1.5, 4.5), 1)
            unit = "ms"
        elif "error" in metric.lower() or "5xx" in metric.lower():
            baseline = round(rng.uniform(0.05, 0.4), 2)
            current = round(baseline * rng.uniform(8, 30), 2)
            unit = "percent"
        elif "memory" in metric.lower():
            baseline = round(rng.uniform(40, 60), 1)
            current = round(rng.uniform(85, 97), 1)
            unit = "percent"
        else:
            baseline = round(rng.uniform(1, 10), 2)
            current = round(baseline * rng.uniform(0.8, 2.0), 2)
            unit = "units"
        return asdict(
            MetricReading(
                metric=metric,
                service=service,
                current_value=current,
                baseline_value=baseline,
                unit=unit,
                window_minutes=window_minutes,
            )
        )


# ---------------------------------------------------------------------------
# OpenAI function-calling schemas
# ---------------------------------------------------------------------------


def tool_schemas() -> List[Dict[str, Any]]:
    """OpenAI-style tools schema for the ReAct agent."""
    return [
        {
            "type": "function",
            "function": {
                "name": "get_recent_deploys",
                "description": "List deploys to a service within a recent time window.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "service": {"type": "string", "description": "Service / deployment name, e.g. 'checkout-service'"},
                        "window_minutes": {"type": "integer", "default": 60},
                    },
                    "required": ["service"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_logs",
                "description": "Fetch a small sample of recent log lines for a service at a given severity.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "service": {"type": "string"},
                        "severity": {"type": "string", "enum": ["error", "warn", "info"], "default": "error"},
                        "limit": {"type": "integer", "default": 5},
                    },
                    "required": ["service"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "check_pod_status",
                "description": "Report kubernetes pod state for a deployment: desired vs ready replicas, restarts in the last hour, last restart reason.",
                "parameters": {
                    "type": "object",
                    "properties": {"deployment": {"type": "string"}},
                    "required": ["deployment"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_metric",
                "description": "Read a metric for a service over a window. Returns current and baseline value.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "metric": {"type": "string", "description": "e.g. 'p99_latency_ms', 'error_rate_percent', 'memory_utilization_percent'"},
                        "service": {"type": "string"},
                        "window_minutes": {"type": "integer", "default": 15},
                    },
                    "required": ["metric", "service"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_runbooks",
                "description": "Search the internal runbook library by free-text query. Returns top-K runbook ids, titles, and bodies.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "k": {"type": "integer", "default": 3},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "propose_plan",
                "description": "TERMINAL action. Once you have enough information, call this to deliver the final response plan. The agent loop stops after this call.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "enum": ["infra", "app", "security", "data"]},
                        "primary_runbook": {"type": ["string", "null"], "description": "id of the runbook used as the basis for the plan, or null"},
                        "steps": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "step": {"type": "string"},
                                    "why": {"type": "string"},
                                },
                                "required": ["step", "why"],
                            },
                        },
                        "summary": {"type": "string", "description": "one sentence summary of what you found and what you are recommending"},
                    },
                    "required": ["category", "steps", "summary"],
                },
            },
        },
    ]


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


@dataclass
class ToolCall:
    name: str
    arguments: Dict[str, Any]
    result: Any = None


def dispatch_tool_call(
    name: str,
    arguments: Dict[str, Any],
    env: MockDevOpsEnv,
    index: RunbookIndex,
) -> Any:
    if name == "get_recent_deploys":
        return env.get_recent_deploys(
            service=arguments["service"],
            window_minutes=arguments.get("window_minutes", 60),
        )
    if name == "query_logs":
        return env.query_logs(
            service=arguments["service"],
            severity=arguments.get("severity", "error"),
            limit=arguments.get("limit", 5),
        )
    if name == "check_pod_status":
        return env.check_pod_status(deployment=arguments["deployment"])
    if name == "get_metric":
        return env.get_metric(
            metric=arguments["metric"],
            service=arguments["service"],
            window_minutes=arguments.get("window_minutes", 15),
        )
    if name == "search_runbooks":
        hits = index.search(arguments["query"], k=arguments.get("k", 3))
        return [
            {
                "runbook_id": h.runbook.runbook_id,
                "title": h.runbook.title,
                "category": h.runbook.category,
                "score": round(h.score, 2),
                "body": h.runbook.text,
            }
            for h in hits
        ]
    raise ValueError(f"unknown tool: {name}")
