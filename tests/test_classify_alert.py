"""Unit tests for the alert-archetype classifier.

Doesn't require an OpenAI key — pure CPU function tests.
"""

from __future__ import annotations

import pytest

from src.tools import classify_alert, extract_service


@pytest.mark.parametrize(
    "alert,expected",
    [
        ("prod-postgres-1 unreachable. Connection pool exhausted.", "database"),
        ("k8s node MemoryPressure=True. 8 pods evicted in the last 5 minutes.", "kubernetes"),
        ("GitGuardian alert: AWS access key AKIA*** committed to public repo.", "secret_leak"),
        ("5xx error rate on /api/checkout is 12%. NullPointerException in PaymentResolver.", "deploy_regression"),
        ("Dashboard 'revenue_today' is stale. Freshness SLA is 15 minutes.", "data_freshness"),
        ("CoreDNS pods in kube-system are CrashLoopBackOff. Service-to-service calls failing.", "dns"),
        ("p99 latency on the search endpoint jumped from 180ms to 1.4s.", "latency"),
        ("User signed in from Lagos and Berlin within 6 minutes, MFA approved both times.", "auth_anomaly"),
        ("Airflow DAG nightly_user_metrics failed; dbt test reported 12 duplicates.", "etl_failure"),
        ("EBS volume at 96% capacity. Filling at ~2GB/min.", "disk"),
        ("Just a generic alert about something unspecified.", "generic"),
        ("2400 failed logins against admin@acme.com from a single ASN in 4 minutes.", "auth_anomaly"),
    ],
)
def test_classifier_routes_alerts_to_expected_archetype(alert: str, expected: str) -> None:
    assert classify_alert(alert) == expected


def test_extract_service_finds_named_service() -> None:
    assert extract_service("the orders-svc is failing") == "orders-svc"


def test_extract_service_returns_none_when_nothing_matches() -> None:
    assert extract_service("Pure latency spike with no service name") is None
