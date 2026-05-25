"""V3: ReAct-style agent with tool use.

Unlike V1 (single classifier call) and V2 (fixed router-then-retrieve-then-plan pipeline),
V3 is genuinely agentic:

- The LLM decides which tool to call next, based on what it has observed so far.
- It can iterate: query logs, see what's wrong, then check pods, then look at metrics,
  then search runbooks, then propose a plan.
- The loop terminates when the LLM calls `propose_plan` (or hits a step budget).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from openai import OpenAI

from .config import PromptConfig, load_prompt_config
from .retrieval import RunbookIndex
from .router import IncidentCategory
from .tools import MockDevOpsEnv, ToolCall, dispatch_tool_call, tool_schemas


@dataclass
class AgentStep:
    role: str  # "assistant" or "tool"
    content: Optional[str] = None
    tool_name: Optional[str] = None
    tool_arguments: Optional[Dict[str, Any]] = None
    tool_result: Optional[Any] = None


@dataclass
class AgentRun:
    alert_text: str
    plan: Optional[Dict[str, Any]] = None
    steps: List[AgentStep] = field(default_factory=list)
    tool_calls: List[ToolCall] = field(default_factory=list)
    terminated_via: str = "max_steps"  # or "propose_plan"
    num_iterations: int = 0


class ReactAgent:
    """A ReAct-style agent: observe → reason → act → observe..."""

    def __init__(
        self,
        index: RunbookIndex,
        client: Optional[OpenAI] = None,
        prompt_config: Optional[PromptConfig] = None,
        model: Optional[str] = None,
        max_iterations: Optional[int] = None,
    ):
        self.index = index
        self.prompt_config = prompt_config or load_prompt_config()
        self.client = client or OpenAI()
        self.model = model or self.prompt_config.agent_model()
        self.system_prompt = self.prompt_config.agent.system
        self.max_iterations = max_iterations or self.prompt_config.agent.max_iterations

    @staticmethod
    def _signature(alert_text: str) -> str:
        return hashlib.sha256(alert_text.encode()).hexdigest()[:16]

    def run(self, alert_text: str) -> AgentRun:
        env = MockDevOpsEnv(alert_text=alert_text)
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"ALERT:\n{alert_text}"},
        ]
        tools = tool_schemas()
        run = AgentRun(alert_text=alert_text)

        for iteration in range(self.max_iterations):
            run.num_iterations = iteration + 1
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="required" if iteration < self.max_iterations - 1 else "auto",
                temperature=0,
            )
            msg = response.choices[0].message
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in (msg.tool_calls or [])
                    ] or None,
                }
            )
            run.steps.append(
                AgentStep(role="assistant", content=msg.content or "")
            )

            if not msg.tool_calls:
                # Model produced a text-only response without a tool call. Treat as terminal.
                run.terminated_via = "text_response"
                break

            terminated = False
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}

                if tc.function.name == "propose_plan":
                    run.plan = args
                    run.tool_calls.append(
                        ToolCall(name=tc.function.name, arguments=args, result="(terminal)")
                    )
                    run.steps.append(
                        AgentStep(
                            role="tool",
                            tool_name=tc.function.name,
                            tool_arguments=args,
                            tool_result="(terminal)",
                        )
                    )
                    run.terminated_via = "propose_plan"
                    terminated = True
                    break

                try:
                    result = dispatch_tool_call(
                        name=tc.function.name,
                        arguments=args,
                        env=env,
                        index=self.index,
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    result = {"error": f"{type(exc).__name__}: {exc}"}

                run.tool_calls.append(
                    ToolCall(name=tc.function.name, arguments=args, result=result)
                )
                run.steps.append(
                    AgentStep(
                        role="tool",
                        tool_name=tc.function.name,
                        tool_arguments=args,
                        tool_result=result,
                    )
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, default=str),
                    }
                )

            if terminated:
                break

        return run

    @staticmethod
    def get_category(run: AgentRun) -> IncidentCategory:
        if run.plan is None:
            return IncidentCategory.UNKNOWN
        cat = str(run.plan.get("category", "")).strip().lower()
        return IncidentCategory(cat) if cat in {c.value for c in IncidentCategory} else IncidentCategory.UNKNOWN

    @staticmethod
    def format_trace(run: AgentRun) -> str:
        """Pretty-print the agent's investigation trace."""
        out = [f"ALERT: {run.alert_text}", f"ITERATIONS: {run.num_iterations}", f"TERMINATED: {run.terminated_via}", ""]
        for i, tc in enumerate(run.tool_calls, 1):
            out.append(f"[{i}] tool: {tc.name}")
            out.append(f"    args:  {json.dumps(tc.arguments, default=str)}")
            if tc.name != "propose_plan":
                short = json.dumps(tc.result, default=str)
                if len(short) > 240:
                    short = short[:240] + "..."
                out.append(f"    -> {short}")
        if run.plan:
            out.append("")
            out.append(f"PLAN: category={run.plan.get('category')}  runbook={run.plan.get('primary_runbook')}")
            out.append(f"SUMMARY: {run.plan.get('summary')}")
            for j, step in enumerate(run.plan.get("steps", []), 1):
                out.append(f"  {j}. {step.get('step')}")
                out.append(f"     why: {step.get('why')}")
        return "\n".join(out)
