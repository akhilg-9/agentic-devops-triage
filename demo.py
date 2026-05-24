"""End-to-end demo: route one alert and produce a plan.

Usage:
    export OPENAI_API_KEY=sk-...
    python demo.py

Or:
    python demo.py "Postgres primary is unreachable and writes are failing across the platform."
"""

from __future__ import annotations

import os
import sys
from dotenv import load_dotenv

from src import PlannerAgent, RouterAgent, RunbookIndex


DEFAULT_ALERT = (
    "k8s nodes in the app-pool are showing MemoryPressure=True and have evicted "
    "15 pods in the last 10 minutes. Cluster autoscaler appears healthy."
)


def main() -> None:
    load_dotenv()
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("set OPENAI_API_KEY (in .env or environment)")

    alert = " ".join(sys.argv[1:]) or DEFAULT_ALERT

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


if __name__ == "__main__":
    main()
