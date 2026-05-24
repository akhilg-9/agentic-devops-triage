# Agentic DevOps Triage

A small, end-to-end **agentic AI system** that triages production-incident alerts and produces a step-by-step response plan grounded in an internal runbook library.

It is built as a two-tier system on a deliberately minimal stack — OpenAI for the LLM, BM25 for retrieval, pandas for evaluation — to make the architecture easy to read.

```
                   ┌────────────────────┐
   incoming alert ─►   V1: Router       │──► category (infra / app / security / data)
                   │   (LLM classifier) │
                   └─────────┬──────────┘
                             │
                             ▼
                   ┌────────────────────┐
                   │   V2: Planner      │
                   │  ┌──────────────┐  │
                   │  │ BM25 search  │──┼──► top-K runbook candidates
                   │  │ over /data/  │  │
                   │  │  runbooks/   │  │
                   │  └──────┬───────┘  │
                   │         ▼          │
                   │   plan generator   │──► structured response plan
                   │       (LLM)        │     {category, runbook, steps[]}
                   └────────────────────┘
```

## Why this exists

Agentic AI demos tend to skip the boring-but-load-bearing part: **how do you know the agent is actually getting better when you change it?**

This project is structured around a tight **CC/CD loop** (Continuous Calibration / Continuous Deployment) for each tier of autonomy:

1. **Build** — implement the baseline.
2. **Test** — run on an eval set, get one number per metric.
3. **Calibrate (CC)** — look at the failures, find the pattern.
4. **Deploy (CD)** — change one thing, re-run, ship only if the delta is positive.

Each notebook walks through the loop once. Each tier (V1 router, V2 planner) ships both a baseline and an improved version so you can see the delta directly.

## Features

- **V1 router** — classifies an alert into `infra` / `app` / `security` / `data`. Baseline and improved prompts; the improved one encodes explicit ordered disambiguation rules.
- **V2 planner** — routes the alert, retrieves top-K runbooks via BM25, and generates a 3–7 step response plan with a short *why* per step.
- **Original runbook corpus** — 10 hand-written runbooks covering Postgres failover, k8s memory pressure, latency spikes, 5xx surges, leaked secrets, suspicious logins, ETL failures, freshness breaches, disk-full, and DNS outages.
- **Evaluation harness** — accuracy + per-category breakdown for routing; recall@1 and recall@k for retrieval; an **LLM-as-judge** that scores each plan on groundedness, completeness, and actionability.
- **Two demo notebooks** — `01_router_agent.ipynb` (V1) and `02_planner_agent.ipynb` (V2), each walking the full CC/CD loop end-to-end.
- **CLI demo** — `python3 demo.py "your alert text here"` for a single end-to-end run with no notebook setup.

## Quick start

```bash
git clone https://github.com/akhilg-9/agentic-devops-triage.git
cd agentic-devops-triage

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and set OPENAI_API_KEY=sk-...

python3 demo.py
```

To run the full evaluation:

```bash
jupyter lab notebooks/
# open 01_router_agent.ipynb, run all cells
# then open 02_planner_agent.ipynb, run all cells
```

## Repository layout

```
agentic-devops-triage/
├── src/
│   ├── router.py         # V1 router agent (OpenAI)
│   ├── retrieval.py      # BM25 index over markdown runbooks
│   ├── planner.py        # V2 planner agent (router + retrieval + LLM)
│   └── evaluation.py     # eval harness + LLM-as-judge
├── notebooks/
│   ├── 01_router_agent.ipynb
│   └── 02_planner_agent.ipynb
├── data/
│   ├── test_cases_v1.csv   # 25 router test cases
│   ├── test_cases_v2.csv   # 15 end-to-end planner test cases
│   └── runbooks/           # 10 markdown runbooks (knowledge base)
├── demo.py
├── requirements.txt
└── .env.example
```

## Metrics tracked

| Tier | Metric | Why |
| --- | --- | --- |
| V1 | overall accuracy | global signal |
| V1 | per-category accuracy | spotting class-imbalance failures |
| V1 | confusion matrix | spotting systematic swaps (e.g., `data` ↔ `infra`) |
| V2 | routing accuracy | V1 still working inside V2 |
| V2 | retrieval recall@1, recall@k | is the right runbook in scope at all? |
| V2 | groundedness (1–5) | did the plan invent steps the runbook does not describe? |
| V2 | completeness (1–5) | does the plan cover triage + mitigation + validation? |
| V2 | actionability (1–5) | can an on-call execute each step without follow-up questions? |

## What's *not* in this repo (intentionally)

- **No fine-tuning.** All wins come from prompt design, retrieval design, and evaluation discipline.
- **No vector DB.** A small, well-written runbook corpus gives BM25 plenty to work with — adding embeddings is a known next step, not a baseline.
- **No agent framework.** The composition is a hundred lines of plain Python. Frameworks are easy to swap in once the eval harness exists.

## Inspiration & attribution

The two-tier architecture and the *Continuous Calibration / Continuous Deployment* framing are inspired by the LinkedIn Learning course **"Agentic AI: Build Your First Agentic AI System"** by Aishwarya Naresh Reganti. **All code, runbooks, test cases, and the DevOps-triage use case in this repo are original** — written from scratch rather than copied or adapted from the course materials.

If you are looking for the course itself, find it on [LinkedIn Learning](https://www.linkedin.com/learning/agentic-ai-build-your-first-agentic-ai-system).

## License

[MIT](./LICENSE).
