"""Streamlit demo for the autonomy-ladder triage system.

Run locally:
    streamlit run app.py

What it does:
- Lets you paste any alert text.
- Picks a tier (V1 router / V2 planner / V3 ReAct agent).
- For V3, streams the agent's tool-call trajectory in real time so you can
  watch the loop investigate.

This is the recruiter-friendly "press play and see it work" view of the repo.
The full evaluation story (CC/CD, the comparison notebook, the eval harness)
lives in the notebooks/ directory.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from src import (
    PlannerAgent,
    ReactAgent,
    RouterAgent,
    RunbookIndex,
    load_prompt_config,
)


# ---------------------------------------------------------------------------
# Cache the heavy stuff so the page is snappy after first load
# ---------------------------------------------------------------------------


@st.cache_resource
def get_runbook_index() -> RunbookIndex:
    return RunbookIndex(runbook_dir="data/runbooks")


@st.cache_resource
def get_router(_version: str) -> RouterAgent:
    return RouterAgent()


@st.cache_resource
def get_planner(_version: str) -> PlannerAgent:
    return PlannerAgent(router=get_router(_version), index=get_runbook_index())


@st.cache_resource
def get_agent(_version: str) -> ReactAgent:
    return ReactAgent(index=get_runbook_index())


# ---------------------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------------------


st.set_page_config(page_title="Agentic DevOps Triage", page_icon="🛎", layout="wide")

st.title("Agentic DevOps Triage")
st.caption(
    "Three tiers on the same incident triage problem. Pick a tier, paste an alert, see what happens."
)

with st.sidebar:
    st.header("Configuration")
    if not os.environ.get("OPENAI_API_KEY"):
        st.error("OPENAI_API_KEY not set. Add it to `.env` and restart.")
    cfg = load_prompt_config()
    st.markdown(f"**Prompt config:** `{cfg.version}`")
    st.markdown(f"**Router model:** `{cfg.router_model()}`")
    st.markdown(f"**Planner model:** `{cfg.planner_model()}`")
    st.markdown(f"**Agent model:** `{cfg.agent_model()}`")
    st.markdown(f"**Max agent iterations:** `{cfg.agent.max_iterations}`")
    st.divider()
    st.markdown(
        "Sample alerts (click to copy):\n\n"
        "- Postgres primary unreachable; orders-svc failing.\n"
        "- k8s MemoryPressure=True; pods evicted from app-pool.\n"
        "- GitGuardian: AWS access key AKIA*** committed to public repo.\n"
        "- p99 latency on /api/search jumped 5x; no recent deploy.\n"
        "- Stripe is reporting elevated 5xx; our /api/charge fails because of it (refusal test).\n"
    )


tier = st.radio(
    "Pick a tier",
    options=["V3 ReAct agent (recommended)", "V2 planner pipeline", "V1 router only"],
    horizontal=True,
)

alert = st.text_area(
    "Alert text",
    height=120,
    placeholder="Paste a production incident alert here…",
)

run = st.button("Triage", type="primary", disabled=not alert.strip())


def _badge(category: str) -> str:
    colors = {"infra": "🟠", "app": "🔵", "security": "🔴", "data": "🟣", "unknown": "⚪"}
    return f"{colors.get(category, '⚪')} **{category}**"


# ---------------------------------------------------------------------------
# Tier dispatch
# ---------------------------------------------------------------------------


if run and alert.strip():
    if tier.startswith("V1"):
        with st.spinner("Routing…"):
            t0 = time.monotonic()
            result = get_router(cfg.version).route(alert)
            elapsed = time.monotonic() - t0
        st.subheader("Result")
        st.markdown(f"Category: {_badge(result.category.value)}")
        if result.rationale:
            st.markdown(f"_Rationale:_ {result.rationale}")
        st.caption(f"completed in {elapsed:.1f}s · 1 LLM call")

    elif tier.startswith("V2"):
        with st.spinner("Routing → retrieving → planning…"):
            t0 = time.monotonic()
            plan = get_planner(cfg.version).plan(alert)
            elapsed = time.monotonic() - t0
        col1, col2 = st.columns([2, 1])
        with col1:
            st.subheader("Plan")
            st.markdown(f"Category: {_badge(plan.category.value)}")
            st.markdown(f"Primary runbook: `{plan.primary_runbook or '(none — escalate)'}`")
            for i, step in enumerate(plan.steps, 1):
                st.markdown(f"**{i}. {step.step}**")
                st.caption(step.why)
        with col2:
            st.subheader("Retrieved runbooks")
            for h in plan.retrieval_hits:
                st.markdown(f"- `{h.runbook.runbook_id}` (BM25 {h.score:.2f})")
                with st.expander("body"):
                    st.text(h.runbook.text[:1200] + ("…" if len(h.runbook.text) > 1200 else ""))
        st.caption(f"completed in {elapsed:.1f}s · 2 LLM calls")

    else:  # V3
        st.subheader("Agent trajectory")
        trace_placeholder = st.empty()
        with st.spinner("Agent investigating…"):
            t0 = time.monotonic()
            run_obj = get_agent(cfg.version).run(alert)
            elapsed = time.monotonic() - t0
        # Render the trace as a step-by-step timeline
        with trace_placeholder.container():
            for i, tc in enumerate(run_obj.tool_calls, 1):
                if tc.name == "propose_plan":
                    st.markdown(f"#### {i}. `propose_plan` _(terminal)_")
                    args = tc.arguments
                    cat = args.get("category", "?")
                    rb = args.get("primary_runbook")
                    summary = args.get("summary", "")
                    st.markdown(f"Category: {_badge(cat)}")
                    st.markdown(f"Primary runbook: `{rb or '(none — escalate)'}`")
                    if summary:
                        st.markdown(f"_Summary:_ {summary}")
                    st.markdown("**Steps:**")
                    for j, step in enumerate(args.get("steps", []), 1):
                        st.markdown(f"  {j}. **{step.get('step')}**")
                        st.caption(step.get("why", ""))
                else:
                    label = f"{i}. `{tc.name}({json.dumps(tc.arguments)[:120]})`"
                    with st.expander(label, expanded=False):
                        st.json(tc.result if isinstance(tc.result, (list, dict)) else {"result": str(tc.result)})
        st.caption(
            f"completed in {elapsed:.1f}s · {run_obj.num_iterations} iterations · "
            f"{len(run_obj.tool_calls)} tool calls · terminated via `{run_obj.terminated_via}`"
        )

else:
    st.info(
        "Pick a tier and paste an alert. V3 is the recommended demo — it's the only tier "
        "that decides which tools to call and in what order."
    )
