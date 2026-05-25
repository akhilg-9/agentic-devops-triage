# Agentic DevOps Triage

A three-tier **agentic AI system** that triages production-incident alerts and produces a step-by-step response plan grounded in an internal runbook library.

The three tiers — `V1 router`, `V2 planner`, `V3 ReAct agent` — implement the three rungs of an "autonomy ladder":

```
          ┌──────────────────────────────────────────┐
   V3  →  │  ReAct agent: tool use + loop            │   ◄─── genuinely agentic
          │  observe → reason → act → observe ...     │
          └──────────────────────────────────────────┘
                              ▲
          ┌──────────────────────────────────────────┐
   V2  →  │  Planner pipeline: route → retrieve → plan│   ◄─── multi-step generation
          └──────────────────────────────────────────┘
                              ▲
          ┌──────────────────────────────────────────┐
   V1  →  │  Router: single classification call       │   ◄─── single decision
          └──────────────────────────────────────────┘
```

Each tier is built and evaluated end-to-end so you can compare them on the same alerts.

## Why three tiers (and not just one)

"Agentic" is overloaded. A single LLM call is not an agent. A fixed three-step pipeline is barely one. **A real agent decides what to do next based on what it has seen.** This repo walks that progression deliberately:

- **V1** — classify the alert into one of four categories. One LLM call. No autonomy beyond the classification itself.
- **V2** — same routing, then BM25 retrieval over runbooks, then plan generation. Multiple stages, but the *order* is hard-coded.
- **V3** — the LLM is handed six tools (`get_recent_deploys`, `query_logs`, `check_pod_status`, `get_metric`, `search_runbooks`, `propose_plan`) and decides which to call, in what order, before committing to a plan. The loop terminates when the agent itself decides it has enough information.

Each tier ships with an evaluation harness so improvements are measured, not asserted.

## What the agent investigates

V3 has read-only tools that simulate the kinds of signals an on-call SRE pulls during triage:

| Tool | Returns |
| --- | --- |
| `get_recent_deploys(service, window_minutes)` | recent deploys with SHAs and authors |
| `query_logs(service, severity, limit)` | sample log lines at the requested severity |
| `check_pod_status(deployment)` | desired/ready replicas, restart count, last restart reason |
| `get_metric(metric, service, window_minutes)` | current vs. baseline value |
| `search_runbooks(query, k)` | BM25 hits over the runbook library |
| `propose_plan(category, primary_runbook, steps, summary)` | **terminal** — emits the final plan |

All non-runbook tools return *mocked-but-realistic* data via a deterministic seed, so notebook runs are reproducible and free of external dependencies.

## Repository layout

```
agentic-devops-triage/
├── src/
│   ├── router.py         # V1 router agent (OpenAI)
│   ├── retrieval.py      # BM25 index over markdown runbooks
│   ├── planner.py        # V2 planner pipeline (router + retrieval + LLM)
│   ├── tools.py          # V3 mocked DevOps tools + OpenAI function schemas
│   ├── agent.py          # V3 ReAct agent (loop with tool calling)
│   └── evaluation.py     # eval harness + LLM-as-judge
├── notebooks/
│   ├── 01_router_agent.ipynb    # V1 build/test/calibrate/deploy
│   ├── 02_planner_agent.ipynb   # V2 build/test/calibrate/deploy
│   └── 03_react_agent.ipynb     # V3 traces, multi-alert comparison, V2 vs. V3
├── data/
│   ├── test_cases_v1.csv        # 25 router test cases
│   ├── test_cases_v2.csv        # 15 end-to-end planner test cases
│   └── runbooks/                # 10 markdown runbooks
├── demo.py
├── requirements.txt
└── .env.example
```

## CC/CD evaluation loop

Each tier is wrapped in the same Continuous-Calibration / Continuous-Deployment loop:

1. **Build** — implement the baseline.
2. **Test** — run on an eval set, get one number per metric.
3. **Calibrate (CC)** — inspect failures, find the systematic pattern.
4. **Deploy (CD)** — change one thing, re-run, ship only on positive delta.

Both V1 and V2 ship a baseline and an improved prompt so the delta is measurable side-by-side.

## Metrics tracked

| Tier | Metric | Why |
| --- | --- | --- |
| V1 | overall + per-category accuracy | global signal + class-imbalance failures |
| V1 | confusion matrix | spot systematic swaps (`data` ↔ `infra`) |
| V2 | routing accuracy | V1 still working inside V2 |
| V2 | retrieval recall@1, recall@k | is the right runbook in scope at all? |
| V2 | groundedness / completeness / actionability (1–5) | LLM-as-judge over the generated plan |
| V3 | number of tool calls per run | efficiency — agent shouldn't grind |
| V3 | terminated_via (`propose_plan` vs `max_steps`) | did the agent know when to stop? |
| V3 | trajectory inspection | qualitative: are the tools chosen sensible for the alert? |

## Quick start

```bash
git clone https://github.com/akhilg-9/agentic-devops-triage.git
cd agentic-devops-triage

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and set OPENAI_API_KEY=sk-...

python3 demo.py                                          # V2 single-alert demo
python3 -c "from src import ReactAgent, RunbookIndex; \
    a = ReactAgent(index=RunbookIndex('data/runbooks')); \
    print(ReactAgent.format_trace(a.run('Postgres primary is unreachable and writes are failing.')))"  # V3 trace
```

Full walkthroughs are in `notebooks/`.

## What's *not* in this repo (intentionally)

- **No fine-tuning.** All gains come from prompt design, retrieval design, evaluation discipline, and tool design.
- **No vector DB.** BM25 over a small, well-written runbook corpus is the right baseline; embeddings are a known next step.
- **No agent framework.** The ReAct loop is ~120 lines of plain Python on top of the OpenAI tool-calling API. Frameworks are easy to swap in once the eval harness exists.
- **No write tools.** V3 only investigates; the highest rung of the autonomy ladder — letting the agent execute against real systems (roll back a deploy, drain a node, open a Jira ticket) — is intentionally out of scope here.

## Inspiration & attribution

The two-tier framing (router + planner) and the *Continuous Calibration / Continuous Deployment* loop are inspired by the LinkedIn Learning course **"Agentic AI: Build Your First Agentic AI System"** by Aishwarya Naresh Reganti. **All code, runbooks, test cases, the DevOps-triage use case, and the V3 ReAct agent in this repo are original** — written from scratch rather than copied or adapted from the course materials.

If you are looking for the course itself, it is on [LinkedIn Learning](https://www.linkedin.com/learning/agentic-ai-build-your-first-agentic-ai-system).

## License

[MIT](./LICENSE).
