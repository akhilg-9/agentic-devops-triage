"""Tests for the ReAct agent loop that don't require a real OpenAI call.

We stub OpenAI's ChatCompletions with a scripted sequence of responses so we
can verify the agent's tool-dispatch + termination behavior end-to-end.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List

import pytest

from src.agent import ReactAgent
from src.retrieval import RunbookIndex
from src.router import IncidentCategory


@dataclass
class _FakeToolCall:
    id: str
    function: Any  # function.name, function.arguments


@dataclass
class _FakeMessage:
    content: str | None
    tool_calls: List[_FakeToolCall] = field(default_factory=list)


@dataclass
class _FakeChoice:
    message: _FakeMessage


@dataclass
class _FakeResponse:
    choices: List[_FakeChoice]


@dataclass
class _FakeFn:
    name: str
    arguments: str


class _ScriptedClient:
    """Returns a fixed list of pre-scripted assistant messages, one per .create() call."""

    def __init__(self, scripted_responses):
        self._responses = list(scripted_responses)
        self.calls_made = 0

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        if not self._responses:
            raise AssertionError("more LLM calls made than scripted responses")
        msg = self._responses.pop(0)
        self.calls_made += 1
        return _FakeResponse(choices=[_FakeChoice(message=msg)])


def _assistant_with_tool_call(name: str, arguments: dict, call_id: str = "tc1") -> _FakeMessage:
    return _FakeMessage(
        content=None,
        tool_calls=[_FakeToolCall(id=call_id, function=_FakeFn(name=name, arguments=json.dumps(arguments)))],
    )


def test_agent_terminates_on_propose_plan_call() -> None:
    index = RunbookIndex(runbook_dir="data/runbooks")
    scripted = [
        _assistant_with_tool_call(
            "propose_plan",
            {
                "category": "infra",
                "primary_runbook": "rb_001_postgres_primary_down",
                "steps": [{"step": "Promote standby", "why": "primary unreachable"}],
                "summary": "promote replica",
            },
        ),
    ]
    client = _ScriptedClient(scripted)
    agent = ReactAgent(index=index, client=client, max_iterations=6)

    run = agent.run("prod-postgres-1 unreachable. Connection refused.")
    assert run.terminated_via == "propose_plan"
    assert run.num_iterations == 1
    assert run.plan is not None
    assert run.plan["category"] == "infra"
    assert ReactAgent.get_category(run) == IncidentCategory.INFRA


def test_agent_can_chain_investigation_then_propose_plan() -> None:
    index = RunbookIndex(runbook_dir="data/runbooks")
    scripted = [
        _assistant_with_tool_call("query_logs", {"service": "postgres", "severity": "error", "limit": 3}, call_id="tc1"),
        _assistant_with_tool_call("search_runbooks", {"query": "postgres primary unreachable", "k": 3}, call_id="tc2"),
        _assistant_with_tool_call(
            "propose_plan",
            {
                "category": "infra",
                "primary_runbook": "rb_001_postgres_primary_down",
                "steps": [{"step": "Promote standby", "why": "primary down"}],
                "summary": "promote replica",
            },
            call_id="tc3",
        ),
    ]
    client = _ScriptedClient(scripted)
    agent = ReactAgent(index=index, client=client, max_iterations=6)

    run = agent.run("prod-postgres-1 unreachable. Connection refused.")
    assert run.terminated_via == "propose_plan"
    # 2 investigative calls + 1 terminal call
    assert [tc.name for tc in run.tool_calls] == ["query_logs", "search_runbooks", "propose_plan"]


def test_agent_max_iterations_caps_runaway_loop() -> None:
    """If the LLM never calls propose_plan, the loop should still terminate."""
    index = RunbookIndex(runbook_dir="data/runbooks")
    scripted = [
        _assistant_with_tool_call("query_logs", {"service": "x", "severity": "error", "limit": 1}, call_id=f"tc{i}")
        for i in range(10)
    ]
    client = _ScriptedClient(scripted)
    agent = ReactAgent(index=index, client=client, max_iterations=3)

    run = agent.run("some alert")
    assert run.terminated_via == "max_steps"
    assert run.num_iterations == 3
