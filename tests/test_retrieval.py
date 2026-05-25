"""Tests for the BM25 runbook index."""

from __future__ import annotations

from src.retrieval import RunbookIndex


def test_index_loads_all_runbooks() -> None:
    idx = RunbookIndex(runbook_dir="data/runbooks")
    assert len(idx.runbooks) >= 10
    titles = {rb.runbook_id for rb in idx.runbooks}
    assert "rb_001_postgres_primary_down" in titles
    assert "rb_010_dns_resolution_failure" in titles


def test_postgres_query_returns_postgres_runbook_first() -> None:
    idx = RunbookIndex(runbook_dir="data/runbooks")
    hits = idx.search("postgres primary unreachable connections failing", k=3)
    assert hits, "no hits returned"
    assert hits[0].runbook.runbook_id == "rb_001_postgres_primary_down"


def test_k8s_query_returns_k8s_runbook() -> None:
    idx = RunbookIndex(runbook_dir="data/runbooks")
    hits = idx.search("kubernetes memory pressure pod evictions", k=3)
    top_3_ids = {h.runbook.runbook_id for h in hits}
    assert "rb_002_kubernetes_node_pressure" in top_3_ids


def test_search_respects_k_parameter() -> None:
    idx = RunbookIndex(runbook_dir="data/runbooks")
    assert len(idx.search("anything at all", k=1)) == 1
    assert len(idx.search("anything at all", k=5)) == 5
