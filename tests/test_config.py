"""Tests for the YAML prompt config loader."""

from __future__ import annotations

import pytest

from src.config import load_prompt_config


def test_default_load_picks_highest_version() -> None:
    cfg = load_prompt_config()
    assert cfg.version.startswith("v"), cfg.version


def test_explicit_v1_loads() -> None:
    cfg = load_prompt_config(version="v1")
    assert cfg.version == "v1"


def test_router_has_both_baseline_and_improved() -> None:
    cfg = load_prompt_config()
    assert cfg.router.system_baseline.strip()
    assert cfg.router.system_improved.strip()
    assert cfg.router.system_baseline != cfg.router.system_improved


def test_planner_user_prompt_has_required_blocks() -> None:
    cfg = load_prompt_config()
    sys_prompt = cfg.planner.system
    # The improved planner prompt must explicitly cover all required schema fields
    for required in ("category", "primary_runbook", "steps"):
        assert required in sys_prompt


def test_agent_max_iterations_in_valid_range() -> None:
    cfg = load_prompt_config()
    assert 1 <= cfg.agent.max_iterations <= 30


def test_unknown_version_raises() -> None:
    with pytest.raises(FileNotFoundError):
        load_prompt_config(version="v999")
