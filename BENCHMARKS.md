# BENCHMARKS.md

All measurements live here. Numbers come from real runs; placeholders are marked `TBD` and updated when the corresponding run happens.

## Datasets

| Dataset | Items | Refusal items | Notes |
| :-- | :--: | :--: | :-- |
| `data/test_cases_v1.csv` | 30 | 5 | router input + expected category |
| `data/test_cases_v2.csv` | 20 | 5 | planner / agent input + expected (category, runbook); refusal rows have empty expected_runbook |
| `data/runbooks/` | 10 | — | infra / app / security / data coverage |

## Tier comparison (notebooks/04_tier_comparison.ipynb)

Same 20 alerts, three tiers, OpenAI `gpt-4o-mini` (router + planner + agent) and `gpt-4o` (judge).

| Tier | Routing acc. | Recall@1 | Recall@k | Refusal acc. | Avg groundedness | Avg LLM/tool calls | Per-alert s |
| :-- | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| V1 router | TBD | — | — | n/a (no refusal mechanism) | — | 1.0 | TBD |
| V2 planner | TBD | TBD | TBD | TBD | TBD | 2.0 | TBD |
| V3 ReAct agent | TBD | — | TBD | TBD | n/a (not judged here) | TBD | TBD |

**Expected pattern** (validate after running):
- V1 routing accuracy ~85–90% — it doesn't model refusal, so refusal alerts get misclassified into the nearest category.
- V2 inherits V1's routing but adds retrieval. Recall@k high (≥0.85) on in-distribution alerts. Refusal accuracy depends entirely on whether the planner prompt is strict enough about `primary_runbook=null`; with prompts/v1.yaml the prompt does instruct refusal, so refusal accuracy should be 0.4–0.8.
- V3 should dominate refusal accuracy because the agent can actually call `search_runbooks` and observe zero relevant hits before committing to a plan. Expected refusal accuracy ≥0.8.

## Per-archetype mock-tool data quality (Phase 2)

Validated by `tests/test_mock_env.py`. These are structural assertions, not numbers — they pass or fail in CI.

| Archetype | Logs returned reference | Pod state | Elevated metric |
| :-- | :-- | :-- | :-- |
| database | postgres / psycopg / WAL / replication | sometimes unhealthy | latency, error_rate |
| kubernetes | OOMKilled / evicted / liveness | unhealthy with OOMKilled/Evicted/CrashLoopBackOff | memory |
| deploy_regression | NullPointerException / TypeError | unhealthy with CrashLoopBackOff/Error | latency, error_rate |
| latency | upstream timeout / cache miss | sometimes unhealthy | latency |
| secret_leak | GitGuardian / AWS_ACCESS_KEY / Stripe | healthy | — |
| auth_anomaly | impossible-travel / failed-logins | healthy | — |
| etl_failure | dbt test fail / schema drift | healthy | freshness |
| data_freshness | freshness SLA breach / kafka lag | healthy | freshness |
| disk | no space left / EBS at 97% | healthy | disk_usage |
| dns | no such host / coredns crashloop | healthy | — |

## End-to-end ask latency (single-alert, `lci ask`)

Apple Silicon M-series, default models:

| Tier | p50 ms | p95 ms | notes |
| :-- | :-: | :-: | :-: |
| V1 router | TBD | TBD | single OpenAI call |
| V2 planner | TBD | TBD | router call + retrieval (CPU) + planner call |
| V3 ReAct agent | TBD | TBD | 3–5 LLM calls + N tool calls on average |

## CI

| Workflow | Trigger | Avg duration |
| :-- | :-- | :-: |
| `.github/workflows/ci.yml` (unit) | PR / push-to-main / dispatch | TBD |

Populate after the first CI run completes.
