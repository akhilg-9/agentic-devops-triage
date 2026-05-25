"""Mock DevOps tools for the V3 ReAct agent.

Phase-2 upgrade: tools are now **alert-aware**. We classify the alert into an
incident archetype (database / kubernetes / deploy / secret / etl / dns /
auth / generic) and return signals whose *content* matches that archetype,
so a "Postgres down" alert sees Postgres-flavored errors when the agent calls
query_logs, OOMKilled events when it checks pods on a memory-pressure alert,
and so on.

This makes the agent's investigation visibly correct in traces rather than
just internally consistent.

All non-runbook tools are deterministic (seeded by alert text + arguments) so
notebook runs reproduce. Real prod systems are never touched.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

from .retrieval import RunbookIndex


# ---------------------------------------------------------------------------
# Alert archetype classification (heuristic, intentionally simple)
# ---------------------------------------------------------------------------


ALERT_ARCHETYPES = [
    "database",
    "kubernetes",
    "deploy_regression",
    "latency",
    "secret_leak",
    "auth_anomaly",
    "etl_failure",
    "data_freshness",
    "disk",
    "dns",
    "generic",
]


# Keywords are (term, weight). Domain-specific terms ("coredns", "akia", "pg_isready")
# weight 3; common but useful terms weight 2; weak generic hits weight 1.
_ARCHETYPE_KEYWORDS: List[Tuple[str, List[Tuple[str, int]]]] = [
    ("database",         [
        ("postgres", 3), ("mysql", 3), ("rds", 3), ("pg_isready", 3),
        ("primary db", 3), ("primary postgres", 3), ("replication slot", 3),
        ("connection refused", 2), ("database", 2), ("wal", 2), ("replica", 1),
    ]),
    ("kubernetes",       [
        ("memorypressure", 3), ("evicted", 3), ("oomkilled", 3),
        ("crashloopbackoff", 3), ("autoscaler", 3), ("imagepullbackoff", 3),
        ("kubectl", 2), ("kubernetes", 2), ("k8s", 2),
        ("pod", 1), ("node", 1), ("deployment", 1),
    ]),
    ("deploy_regression",[
        ("nullpointerexception", 3), ("stack trace", 3), ("rollback", 3),
        ("typeerror", 3), ("regression", 3),
        ("5xx", 2), ("error rate", 2), ("exception", 2), ("nullpointer", 2),
        ("after the", 2), ("since the", 2), ("rolled out", 2), ("shipped", 2),
        ("deploy", 1), ("release", 1), ("500", 1),
    ]),
    ("latency",          [
        ("p99", 3), ("p95", 3), ("lcp", 3), ("web vitals", 3),
        ("latency", 2), ("ttfb", 2), ("timeout", 2),
        ("slow", 1),
    ]),
    ("secret_leak",      [
        ("akia", 3), ("gitguardian", 3), ("stripe live", 3),
        ("aws access key", 3), ("exposed key", 3), ("key committed", 3),
        ("secret-scanning", 3),
        ("credential", 2), ("leaked", 2), ("secret", 2),
    ]),
    ("auth_anomaly",     [
        ("impossible-travel", 3), ("impossible travel", 3), ("brute-force", 3),
        ("brute force", 3), ("account takeover", 3),
        ("mfa", 2), ("sso", 2), ("takeover", 2),
        ("login", 1), ("session", 1), ("auth", 1),
    ]),
    ("etl_failure",      [
        ("airflow", 3), ("dbt test", 3), ("schema drift", 3),
        ("dbt", 2), ("dag", 2), ("etl", 2), ("pipeline failed", 2),
        ("duplicates", 1),
    ]),
    ("data_freshness",   [
        ("freshness sla", 3), ("max(updated_at)", 3), ("data freshness", 3),
        ("freshness", 2), ("stale", 2), ("lag exceeds", 2),
    ]),
    ("disk",             [
        ("no space left", 3), ("ebs volume", 3), ("filling at", 3),
        ("disk", 2), ("df -h", 2), ("volume", 1),
    ]),
    ("dns",              [
        ("coredns", 3), ("kube-dns", 3), ("name resolution", 3), ("no such host", 3),
        ("dns", 2), ("lookup", 1),
    ]),
]


def classify_alert(alert_text: str) -> str:
    """Return the most likely archetype based on weighted keyword scoring.

    Domain-specific terms outweigh generic infra terms, so "CoreDNS in
    CrashLoopBackOff" lands on `dns` (not `kubernetes`), and "5xx error rate
    + NullPointerException" lands on `deploy_regression` (not `generic`).
    """
    text = alert_text.lower()
    best: Tuple[str, int] = ("generic", 0)
    for archetype, weighted_keywords in _ARCHETYPE_KEYWORDS:
        score = sum(weight for term, weight in weighted_keywords if term in text)
        if score > best[1]:
            best = (archetype, score)
    return best[0]


def extract_service(alert_text: str) -> Optional[str]:
    """Pull out a plausible service / deployment name from the alert text."""
    # Common patterns: 'svc', 'service', or hostname-like tokens with dashes.
    m = re.search(r"\b([a-z0-9][a-z0-9-]{2,}-(?:svc|service|api|worker|web|app|pool|deployment))\b", alert_text.lower())
    if m:
        return m.group(1)
    m = re.search(r"\b([a-z][a-z0-9-]{4,})\s+(?:service|deployment|pod|pods|node|nodes)\b", alert_text.lower())
    if m:
        return m.group(1)
    m = re.search(r"\b(prod-[a-z0-9-]{3,})\b", alert_text.lower())
    if m:
        return m.group(1)
    return None


# ---------------------------------------------------------------------------
# Mocked environment
# ---------------------------------------------------------------------------


def _seeded_rng(*parts: str) -> random.Random:
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


# ---- Per-archetype log templates ----

_LOG_TEMPLATES: Dict[str, Dict[str, List[str]]] = {
    "database": {
        "error": [
            "psycopg2.OperationalError: connection to server at \"{svc}\" failed: Connection refused",
            "FATAL: remaining connection slots are reserved for non-replication superuser connections",
            "could not connect to database {svc}: server closed the connection unexpectedly",
            "WAL segment 000000010000004A0000007F lost; replication slot bytes growing",
        ],
        "warn": [
            "slow query: SELECT * FROM orders WHERE created_at > $1 (3400ms)",
            "replica lag against primary: 12s",
        ],
        "info": [
            "vacuum on table users completed in 4.2s",
        ],
    },
    "kubernetes": {
        "error": [
            "Evicted: The node was low on resource: memory. Container {svc} was using 612Mi.",
            "OOMKilled: container {svc} exceeded memory limit 512Mi",
            "Liveness probe failed: HTTP probe failed with statuscode: 503",
            "Back-off restarting failed container",
        ],
        "warn": [
            "Pod {svc}-7d4f8c-x9k2j has been pending for 8 minutes",
            "FailedScheduling: 0/12 nodes are available: 12 Insufficient memory",
        ],
        "info": [
            "Successfully assigned default/{svc}-7d4f8c-x9k2j to ip-10-0-3-14",
        ],
    },
    "deploy_regression": {
        "error": [
            "NullPointerException at com.acme.checkout.PaymentResolver.resolve (line 142) — introduced in commit a91f3c2",
            "TypeError: Cannot read properties of undefined (reading 'map') at ProductGrid.jsx:88",
            "panic: assignment to entry in nil map [recovered] goroutine /handler.go:212",
        ],
        "warn": [
            "Feature flag checkout_v2 enabled at 14:02 UTC; error spike correlates",
        ],
        "info": [
            "Deploy completed: revision r-2026.05.24-1402, 12/12 pods ready",
        ],
    },
    "latency": {
        "error": [
            "Upstream timeout calling {svc}-api after 30000ms",
            "context deadline exceeded",
        ],
        "warn": [
            "p99 latency 1842ms vs baseline 213ms over the last 10m",
            "Cache hit rate dropped from 94% to 31% on {svc}",
            "Redis pool exhausted: in_use=64/64",
        ],
        "info": [
            "Trace 7f3a... spent 1.6s in downstream call to inventory-svc",
        ],
    },
    "secret_leak": {
        "error": [
            "GitGuardian alert: AWS_ACCESS_KEY_ID found in akhilg-9/sandbox@abc1234",
            "Secret-scanner: Stripe live secret pattern detected in public docker image layer",
        ],
        "warn": [
            "IAM key AKIA*** used from new IP 185.220.101.xx (Tor exit) at 14:08 UTC",
            "CloudTrail: DescribeInstances called from unexpected ASN",
        ],
        "info": [
            "Repo akhilg-9/sandbox was made public 17 minutes ago",
        ],
    },
    "auth_anomaly": {
        "error": [
            "MFA approval from device fingerprint 9c2a... not seen before for user@corp",
            "Successful login from Lagos at 14:01, then from Berlin at 14:07 — impossible travel",
        ],
        "warn": [
            "2,400 failed logins against admin@corp from ASN 12345 in 4 minutes",
            "Session for user@corp granted admin scope unexpectedly",
        ],
        "info": [
            "Last legitimate login from user@corp at 09:14 from known device",
        ],
    },
    "etl_failure": {
        "error": [
            "AirflowException: Task failed: dbt test unique_users_user_id (12 duplicates)",
            "Schema drift: column 'tenant_uuid' in source 'public.users' is now NULLABLE",
            "Cannot allocate memory for warehouse query (XL queue full)",
        ],
        "warn": [
            "Upstream CDC slot 'orders_cdc' has been idle 2h17m",
        ],
        "info": [
            "Last successful run of nightly_user_metrics: 2026-05-23 02:14 UTC",
        ],
    },
    "data_freshness": {
        "error": [
            "Freshness SLA breached: max(updated_at) on fct_orders is 3h42m stale (SLA 15m)",
        ],
        "warn": [
            "Kafka topic events.user.* consumer-lag at 9.3M messages",
            "BigQuery partition 2026-05-24 row count 0 (expected ~120k)",
        ],
        "info": [
            "Producer events-api healthy; bottleneck appears downstream",
        ],
    },
    "disk": {
        "error": [
            "No space left on device: /var/log/postgres",
            "EBS volume vol-0abc... at 97% capacity",
        ],
        "warn": [
            "Disk fill rate ~3GB/min on /var/lib/docker on prod-app-12",
        ],
        "info": [
            "Last logrotate ran 18 hours ago",
        ],
    },
    "dns": {
        "error": [
            "lookup kubernetes.default.svc.cluster.local: no such host",
            "Temporary failure in name resolution",
            "coredns pod kube-system/coredns-5b... in CrashLoopBackOff",
        ],
        "warn": [
            "CoreDNS Corefile changed at 13:51 UTC by ops-bot",
        ],
        "info": [
            "Upstream resolver 10.0.0.2 reachable from bastion",
        ],
    },
    "generic": {
        "error": [
            "Generic application error in {svc}",
            "Upstream returned 502",
        ],
        "warn": [
            "Elevated retry rate on {svc}",
        ],
        "info": [
            "{svc} health check OK",
        ],
    },
}


class MockDevOpsEnv:
    """A deterministic, in-memory mock of an SRE environment.

    Classifies the alert into an archetype on construction so every tool call
    returns archetype-flavored data. The same alert + arguments always produce
    the same response, so notebook runs reproduce.
    """

    def __init__(self, alert_text: str):
        self.alert_text = alert_text
        self.archetype = classify_alert(alert_text)
        self.inferred_service = extract_service(alert_text) or "app-svc"
        self._signature = hashlib.sha256(alert_text.encode()).hexdigest()[:16]

    # ---------------- tools ----------------

    def get_recent_deploys(self, service: str, window_minutes: int = 60) -> List[Dict[str, Any]]:
        rng = _seeded_rng(self._signature, "deploys", service, str(window_minutes))
        # deploy_regression alerts almost always have a recent deploy; others, ~30%.
        had_deploy = (self.archetype == "deploy_regression") or rng.random() < 0.30
        if not had_deploy:
            return []
        minutes_ago = rng.randint(2, max(3, window_minutes - 1))
        author = rng.choice(["maya@corp", "leo@corp", "priya@corp", "sam@corp"])
        sha = "".join(rng.choice("abcdef0123456789") for _ in range(7))
        return [asdict(Deploy(service=service, sha=sha, deployed_minutes_ago=minutes_ago, author=author))]

    def query_logs(self, service: str, severity: str = "error", limit: int = 5) -> List[Dict[str, Any]]:
        rng = _seeded_rng(self._signature, "logs", service, severity)
        templates = _LOG_TEMPLATES.get(self.archetype, _LOG_TEMPLATES["generic"])
        pool = templates.get(severity) or templates.get("error") or []
        if not pool:
            return []
        lines: List[LogLine] = []
        for _ in range(min(limit, len(pool))):
            msg = rng.choice(pool).replace("{svc}", service or self.inferred_service)
            lines.append(LogLine(timestamp_minutes_ago=rng.randint(0, 25), severity=severity, message=msg))
        # de-dup by message, preserve first occurrence
        seen = set()
        unique: List[LogLine] = []
        for line in sorted(lines, key=lambda x: x.timestamp_minutes_ago):
            if line.message in seen:
                continue
            seen.add(line.message)
            unique.append(line)
        return [asdict(line) for line in unique]

    def check_pod_status(self, deployment: str) -> Dict[str, Any]:
        rng = _seeded_rng(self._signature, "pods", deployment)
        desired = rng.choice([6, 8, 10, 12])
        # kubernetes / deploy_regression / latency alerts are likely to show unhealthy pods.
        unhealthy_likely = self.archetype in {"kubernetes", "deploy_regression", "latency"}
        unhealthy = unhealthy_likely or rng.random() < 0.20
        ready = desired - (rng.randint(1, max(1, desired // 3)) if unhealthy else 0)
        if unhealthy:
            restarts = rng.randint(8, 40)
            if self.archetype == "kubernetes":
                last_reason = rng.choice(["OOMKilled", "Evicted", "CrashLoopBackOff"])
            elif self.archetype == "deploy_regression":
                last_reason = rng.choice(["CrashLoopBackOff", "Error"])
            elif self.archetype == "latency":
                last_reason = rng.choice(["Error", "OOMKilled"])
            else:
                last_reason = rng.choice(["OOMKilled", "CrashLoopBackOff", "Error"])
        else:
            restarts = rng.randint(0, 2)
            last_reason = None
        return asdict(PodStatus(
            deployment=deployment,
            desired_replicas=desired,
            ready_replicas=ready,
            restarts_last_hour=restarts,
            last_restart_reason=last_reason,
        ))

    def get_metric(self, metric: str, service: str, window_minutes: int = 15) -> Dict[str, Any]:
        rng = _seeded_rng(self._signature, "metric", metric, service)
        m = metric.lower()
        elevated = False
        # The metric being asked about correlates with the archetype.
        if "latency" in m or "p99" in m or "p95" in m:
            elevated = self.archetype in {"latency", "database", "dns", "deploy_regression"}
            baseline = round(rng.uniform(120, 240), 1)
            current = round(baseline * (rng.uniform(2.5, 6.0) if elevated else rng.uniform(0.9, 1.4)), 1)
            unit = "ms"
        elif "error" in m or "5xx" in m:
            elevated = self.archetype in {"deploy_regression", "database", "dns"}
            baseline = round(rng.uniform(0.05, 0.4), 2)
            current = round(baseline * (rng.uniform(15, 40) if elevated else rng.uniform(0.8, 2.0)), 2)
            unit = "percent"
        elif "memory" in m:
            elevated = self.archetype == "kubernetes"
            baseline = round(rng.uniform(40, 60), 1)
            current = round(rng.uniform(85, 97) if elevated else rng.uniform(45, 70), 1)
            unit = "percent"
        elif "disk" in m or "volume" in m:
            elevated = self.archetype == "disk"
            baseline = round(rng.uniform(40, 60), 1)
            current = round(rng.uniform(92, 98) if elevated else rng.uniform(45, 75), 1)
            unit = "percent"
        elif "freshness" in m or "lag" in m:
            elevated = self.archetype in {"data_freshness", "etl_failure"}
            baseline = round(rng.uniform(0.5, 5.0), 2)
            current = round(rng.uniform(120, 600) if elevated else rng.uniform(0.5, 8.0), 2)
            unit = "minutes"
        else:
            baseline = round(rng.uniform(1, 10), 2)
            current = round(baseline * rng.uniform(0.8, 2.0), 2)
            unit = "units"
        return asdict(MetricReading(
            metric=metric,
            service=service,
            current_value=current,
            baseline_value=baseline,
            unit=unit,
            window_minutes=window_minutes,
        ))


# ---------------------------------------------------------------------------
# OpenAI function-calling schemas
# ---------------------------------------------------------------------------


def tool_schemas() -> List[Dict[str, Any]]:
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
                        "metric": {"type": "string", "description": "e.g. 'p99_latency_ms', 'error_rate_percent', 'memory_utilization_percent', 'disk_usage_percent', 'freshness_minutes'"},
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
