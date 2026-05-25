"""End-to-end demo: investigate an alert and produce a plan.

By default runs the V3 ReAct agent so you can see the autonomous tool-use trace.
Pass --tier v2 to run the V2 pipeline instead.

Usage:
    export OPENAI_API_KEY=sk-...
    python3 demo.py
    python3 demo.py "Postgres primary is unreachable; writes failing."
    python3 demo.py --tier v2 "Postgres primary is unreachable; writes failing."
"""

from __future__ import annotations

import os
import sys
from dotenv import load_dotenv

from src import PlannerAgent, ReactAgent, RouterAgent, RunbookIndex


DEFAULT_ALERT = (
    "k8s nodes in the app-pool are showing MemoryPressure=True and have evicted "
    "15 pods in the last 10 minutes. Cluster autoscaler appears healthy."
)


def run_v3(alert: str) -> None:
    index = RunbookIndex(runbook_dir="data/runbooks")
    agent = ReactAgent(index=index)
    run = agent.run(alert)
    print(ReactAgent.format_trace(run))


def run_v2(alert: str) -> None:
    router = RouterAgent(prompt_version="improved")
    index = RunbookIndex(runbook_dir="data/runbooks")
    planner = PlannerAgent(router=router, index=index, prompt_version="improved")
    plan = planner.plan(alert)
    print(f"ALERT:\n  {alert}\n")
    print(f"CATEGORY:          {plan.category.value}")
    print(f"PRIMARY RUNBOOK:   {plan.primary_runbook}")
    print(f"TOP-3 BM25 HITS:")
    for hit in plan.retrieval_hits:
        print(f"  - {hit.runbook.runbook_id:<40s} score={hit.score:6.2f}  {hit.runbook.title}")
    print("\nRESPONSE PLAN:")
    for i, step in enumerate(plan.steps, 1):
        print(f"  {i}. {step.step}")
        print(f"     why: {step.why}")


def main() -> None:
    load_dotenv()
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("set OPENAI_API_KEY (in .env or environment)")

    args = sys.argv[1:]
    tier = "v3"
    if args and args[0] == "--tier":
        tier = args[1]
        args = args[2:]
    alert = " ".join(args) or DEFAULT_ALERT

    if tier == "v3":
        run_v3(alert)
    elif tier == "v2":
        run_v2(alert)
    else:
        sys.exit(f"unknown tier: {tier} (expected v2 or v3)")


if __name__ == "__main__":
    main()
