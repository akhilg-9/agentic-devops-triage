# Agentic DevOps Triage

[![CI](https://github.com/akhilg-9/agentic-devops-triage/actions/workflows/ci.yml/badge.svg)](https://github.com/akhilg-9/agentic-devops-triage/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

> A three-tier **autonomy-ladder** demo: route → plan → ReAct agent. Each tier is built and evaluated against the same alerts so the progression is measurable, not hand-waved.

**Jump to:** [Why three tiers](#why-three-tiers) · [Architecture](#architecture) · [Quick start](#quick-start) · [Streamlit demo](#streamlit-demo) · [CLI](#cli) · [Evaluation](#evaluation) · [Configuration](#configuration)

---

## Why three tiers

"Agentic" is overloaded — a single LLM call isn't an agent; a fixed three-step pipeline barely is. **A real agent decides what to do next based on what it has seen.** This repo walks the ladder deliberately:

| Tier | What it is | Agentic? |
| :-: | :-- | :-: |
| **V1 router** | one LLM classification call into `infra/app/security/data` | no — classifier |
| **V2 planner** | router → BM25 retrieve → plan generator (fixed order) | not really — fixed pipeline |
| **V3 ReAct agent** | LLM is handed 6 tools, decides which to call, when to stop | **yes** |

The comparison notebook (`notebooks/04_tier_comparison.ipynb`) runs all three on the same 20 alerts and emits **one** table showing how routing accuracy, retrieval recall, refusal accuracy, tool-call count, and latency change as you climb the ladder.

---

## Architecture

```
          ┌──────────────────────────────────────────┐
   V3  →  │  ReAct agent: tool use + loop            │   ◄── genuinely agentic
          │  observe → reason → act → observe ...    │
          └──────────────────────────────────────────┘
                              ▲
          ┌──────────────────────────────────────────┐
   V2  →  │  Planner pipeline: route → retrieve → plan│   ◄── multi-step generation
          └──────────────────────────────────────────┘
                              ▲
          ┌──────────────────────────────────────────┐
   V1  →  │  Router: single classification call       │   ◄── single decision
          └──────────────────────────────────────────┘
```

**V3 tools** (read-only, mocked-but-realistic):

| Tool | Returns |
| :-- | :-- |
| `get_recent_deploys(service, window_minutes)` | recent deploys with SHAs + authors |
| `query_logs(service, severity, limit)` | sample log lines — archetype-flavored |
| `check_pod_status(deployment)` | desired/ready replicas, restart count, last restart reason |
| `get_metric(metric, service, window_minutes)` | current vs. baseline value |
| `search_runbooks(query, k)` | BM25 hits over the runbook library |
| `propose_plan(category, primary_runbook, steps, summary)` | **terminal** — emits the final plan |

**Alert-aware mocks:** The mock environment classifies the alert into one of 10 archetypes (database, kubernetes, deploy_regression, latency, secret_leak, auth_anomaly, etl_failure, data_freshness, disk, dns, generic) and returns archetype-flavored data — Postgres errors for Postgres alerts, OOMKilled events for k8s memory alerts, GitGuardian audit entries for leaked-credential alerts. The agent's investigation visibly tracks the *right* signals for the alert at hand.

---

## Quick start

```bash
git clone https://github.com/akhilg-9/agentic-devops-triage.git
cd agentic-devops-triage

python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[ui,notebooks,dev]"

cp .env.example .env
# set OPENAI_API_KEY=sk-...

# CLI
triage agent "prod-postgres-1 unreachable. Connection pool exhausted on orders-svc."
triage plan "5xx error rate on /api/checkout 12%. NullPointerException."
triage route "GitGuardian: AWS access key AKIA*** committed to public repo."

# Streamlit web demo (see screenshot section below)
streamlit run app.py

# Notebooks
jupyter lab notebooks/
```

---

## Streamlit demo

```bash
streamlit run app.py
```

Pick a tier, paste an alert, watch what happens. V3's expanded tool calls show each step of the agent's investigation:

```
1. query_logs(service="postgres", severity="error", limit=3)
   → [{"message": "psycopg2.OperationalError: connection refused", "severity": "error", …}, …]
2. search_runbooks(query="postgres primary unreachable", k=3)
   → [{"runbook_id": "rb_001_postgres_primary_down", "score": 9.41, …}, …]
3. propose_plan (terminal)
   → category: infra
     primary_runbook: rb_001_postgres_primary_down
     steps:
       1. Promote freshest replica via pg_promote()
       2. Update connection-pool DNS to new primary
       3. …
```

---

## CLI

```text
triage route "<alert>"        V1 router only
triage plan  "<alert>"        V2 planner pipeline (router + retrieval + plan)
triage agent "<alert>"        V3 ReAct agent — streams investigation trace
triage list-runbooks          show ingested runbooks
triage info                   show active prompt config + models
```

All three commands accept `--prompt v1` to pin a specific prompt config. `triage agent` also takes `--max-iter` to cap the loop manually.

---

## Evaluation

**Data:**
- `data/test_cases_v1.csv` — 30 router cases including 5 alerts whose correct action is to escalate
- `data/test_cases_v2.csv` — 20 planner cases (15 in-distribution + 5 refusal — no matching runbook)
- `data/runbooks/` — 10 markdown runbooks covering Postgres, k8s, latency, 5xx, secrets, suspicious-login, ETL, freshness, disk, DNS

**Metrics:**

| Metric | Source | What it catches |
| :-- | :-- | :-- |
| `routing_accuracy` | structural | per-tier router decision matches expected category |
| `recall@1`, `recall@k` | structural | expected runbook is in top-1 / top-k retrieval |
| `refusal_accuracy` | structural | refusal-case alerts get `primary_runbook=null` (correct escalation) |
| `groundedness / completeness / actionability` (1–5) | LLM-as-judge | plan quality vs. the ground-truth runbook |
| `tool_calls`, `iterations` | V3 only | how hard the agent worked per alert |
| `wall_clock_s` | structural | per-alert latency |

The comparison notebook prints one table with a row per tier; per-alert detail is in `04_tier_comparison.ipynb`'s "disagreements" cell — the alerts where V2 and V3 reach different conclusions.

**Per-tier notebooks** also exist (`01_router_agent.ipynb`, `02_planner_agent.ipynb`, `03_react_agent.ipynb`) and walk through each tier's **CC/CD** (continuous-calibration / continuous-deployment) loop — build → test → calibrate → deploy.

---

## Versioned prompt configs

Every prompt + retrieval setting lives in `prompts/v*.yaml`. Bumping the file is the unit of change for evaluation. Same shape as the legal-contract-intelligence repo so iteration discipline is consistent across the portfolio.

```yaml
# excerpt — prompts/v1.yaml
version: v1
model:
  provider: openai
  router_model: gpt-4o-mini
  planner_model: gpt-4o-mini
  agent_model: gpt-4o-mini
  judge_model: gpt-4o
  temperature: 0.0
retrieval:
  top_k: 3
router:
  prompt_version: improved          # baseline | improved (A/B within v1)
  system_baseline: |
    You are a DevOps incident router. ...
  system_improved: |
    You are a senior on-call engineer. Disambiguation rules:
    1. Credentials / secrets → security.
    2. Data correctness / freshness / dbt → data.
    ...
agent:
  max_iterations: 6
  system: |
    You are an autonomous on-call SRE. ...
```

Env overrides (`ROUTER_MODEL`, `PLANNER_MODEL`, `AGENT_MODEL`, `JUDGE_MODEL`) win over the YAML, so you can A/B without editing config.

---

## Tests + CI

```bash
pytest tests/ -v
```

What's covered:
- `test_classify_alert.py` — alert-archetype classifier on 12 cases.
- `test_mock_env.py` — defends Phase 2's central claim: tool outputs correlate with alert archetype, and the env is deterministic.
- `test_retrieval.py` — BM25 index loads all runbooks and returns the right one for canonical queries.
- `test_config.py` — YAML prompt config loader.
- `test_agent_loop.py` — scripted-client tests of the ReAct loop (termination, tool chaining, max-iteration cap). No real OpenAI calls.

CI: `.github/workflows/ci.yml` runs `pytest tests/` on every PR and push to `main`. No API key required for unit tests.

---

## Configuration

| Setting | Default | Notes |
| :-- | :-- | :-- |
| `OPENAI_API_KEY` | _(required)_ | for real triage runs |
| `ROUTER_MODEL` / `PLANNER_MODEL` / `AGENT_MODEL` | _(from YAML)_ | env overrides win over YAML |
| `JUDGE_MODEL` | _(from YAML)_ | LLM-as-judge for plan grading |
| `TRIAGE_PROMPTS_DIR` | `prompts` | location of v*.yaml configs |
| `TRIAGE_RUNBOOK_DIR` | `data/runbooks` | location of markdown runbooks |

---

## Repository layout

```
agentic-devops-triage/
├── prompts/
│   └── v1.yaml                  # versioned prompt + model + retrieval config
├── src/
│   ├── config.py                # PromptConfig (pydantic) + env Settings
│   ├── router.py                # V1 router agent
│   ├── retrieval.py             # BM25 over markdown runbooks
│   ├── planner.py               # V2 planner pipeline
│   ├── tools.py                 # alert-aware mock env + function schemas
│   ├── agent.py                 # V3 ReAct loop
│   ├── evaluation.py            # eval harness + LLM-as-judge
│   └── cli.py                   # `triage` typer CLI
├── notebooks/
│   ├── 01_router_agent.ipynb    # V1 build/test/calibrate/deploy
│   ├── 02_planner_agent.ipynb   # V2 build/test/calibrate/deploy
│   ├── 03_react_agent.ipynb     # V3 traces + multi-alert + V2-vs-V3
│   └── 04_tier_comparison.ipynb # all three tiers on the same set — headline result
├── tests/
│   ├── test_classify_alert.py
│   ├── test_mock_env.py
│   ├── test_retrieval.py
│   ├── test_config.py
│   └── test_agent_loop.py
├── data/
│   ├── runbooks/                # 10 incident response runbooks
│   ├── test_cases_v1.csv        # 30 router cases (5 refusals)
│   └── test_cases_v2.csv        # 20 planner cases (5 refusals)
├── app.py                       # Streamlit demo
├── demo.py                      # CLI demo of V3 (legacy; prefer `triage agent`)
├── .github/workflows/ci.yml
├── pyproject.toml
├── requirements.txt
├── .env.example
├── BENCHMARKS.md                # measurements
└── WHAT_BROKE.md                # honest iteration log
```

---

## What's intentionally NOT in this repo

- **No write tools.** V3 only investigates; it doesn't execute against real systems.
- **No agent framework.** The ReAct loop is ~120 lines on top of OpenAI tool calling. Easy to swap in LangGraph / LlamaIndex later.
- **No real prod integrations.** Tools are mocked. The point is the architecture and evaluation discipline; pointing the mocks at real Prometheus / Loki / k8s clients is a thin shim away.

---

## Inspiration & attribution

The router + planner shape is inspired by LinkedIn Learning's "Agentic AI: Build Your First Agentic AI System" by Aishwarya Naresh Reganti. **All code, runbooks, test data, and the V3 ReAct agent are original** — this is a from-scratch portfolio project, not adapted from course materials.

---

## License

[MIT](./LICENSE). Built by [@akhilg-9](https://github.com/akhilg-9).
