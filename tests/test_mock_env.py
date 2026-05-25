"""Tests that mocked tool data correlates with the alert archetype.

This is the test that defends Phase-2's central claim: query_logs against a
Postgres alert returns Postgres errors, against a k8s alert returns
OOMKilled events, etc.
"""

from __future__ import annotations

import pytest

from src.tools import MockDevOpsEnv


def test_database_alert_returns_postgres_flavored_logs() -> None:
    env = MockDevOpsEnv("prod-postgres-1 unreachable. Connection pool exhausted on orders-svc.")
    assert env.archetype == "database"
    logs = env.query_logs(service="orders-svc", severity="error", limit=4)
    joined = " ".join(line["message"].lower() for line in logs)
    assert any(keyword in joined for keyword in ["postgres", "psycopg", "wal", "replication"])


def test_kubernetes_alert_returns_oom_or_eviction_logs() -> None:
    env = MockDevOpsEnv("k8s nodes show MemoryPressure=True and 15 pods evicted")
    assert env.archetype == "kubernetes"
    logs = env.query_logs(service="app-svc", severity="error", limit=4)
    joined = " ".join(line["message"].lower() for line in logs)
    assert any(keyword in joined for keyword in ["oomkilled", "evicted", "memory limit", "liveness", "back-off"])


def test_secret_leak_alert_returns_credential_flavored_logs() -> None:
    env = MockDevOpsEnv("GitGuardian: AWS access key AKIA*** committed to public repo")
    assert env.archetype == "secret_leak"
    logs = env.query_logs(service="audit", severity="error", limit=4)
    joined = " ".join(line["message"].lower() for line in logs)
    assert any(keyword in joined for keyword in ["gitguardian", "aws_access_key", "stripe", "secret-scanner"])


def test_metric_elevated_only_when_archetype_matches() -> None:
    db_env = MockDevOpsEnv("prod-postgres-1 unreachable. Connection refused.")
    generic_env = MockDevOpsEnv("Just a generic alert about something.")
    # p99 latency should be elevated for a database outage but baseline-ish for a generic alert
    db_metric = db_env.get_metric(metric="p99_latency_ms", service="orders-svc")
    gen_metric = generic_env.get_metric(metric="p99_latency_ms", service="orders-svc")
    assert db_metric["current_value"] > db_metric["baseline_value"]
    # Generic alerts get the catch-all branch with ~0.8-2x baseline. Allow either side.
    assert gen_metric["current_value"] / gen_metric["baseline_value"] < 2.5


def test_disk_alert_makes_disk_metric_high() -> None:
    env = MockDevOpsEnv("EBS volume vol-0abc at 97% capacity, filling at 3GB/min")
    assert env.archetype == "disk"
    metric = env.get_metric(metric="disk_usage_percent", service="prod-app-12")
    assert metric["current_value"] >= 90.0


def test_kubernetes_alert_makes_pods_unhealthy() -> None:
    env = MockDevOpsEnv("k8s node MemoryPressure=True. 8 pods evicted in 5 min.")
    pods = env.check_pod_status(deployment="app-pool")
    assert pods["ready_replicas"] < pods["desired_replicas"]
    assert pods["last_restart_reason"] in {"OOMKilled", "Evicted", "CrashLoopBackOff"}


def test_deterministic_for_same_alert_and_args() -> None:
    """Re-instantiating the env on the same alert should produce identical responses."""
    a = MockDevOpsEnv("prod-postgres-1 unreachable. Connection refused.")
    b = MockDevOpsEnv("prod-postgres-1 unreachable. Connection refused.")
    assert a.query_logs("svc-a", "error", 3) == b.query_logs("svc-a", "error", 3)
    assert a.check_pod_status("dep-x") == b.check_pod_status("dep-x")
    assert a.get_metric("p99_latency_ms", "svc-a") == b.get_metric("p99_latency_ms", "svc-a")
