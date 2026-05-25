# WHAT_BROKE.md

Honest log of friction and dead ends across the project. The kind of detail that signals iteration, not just delivery.

## Initial build (V1 + V2 + V3)

- **"5xx surge" alert kept getting classified as `generic`.** The first version of the alert-archetype classifier did simple unweighted keyword counting. An alert like "5xx error rate 12%, NullPointerException in PaymentResolver" only matched two generic words ("rate", "error") and one in `deploy_regression` ("the") — neither cleared the threshold. Fixed by switching to weighted keyword scoring where domain-specific terms (`nullpointerexception`, `5xx`, `stack trace`) count weight 3, common terms count weight 2, weak terms count weight 1. The classifier now lands `5xx surge + NullPointerException` on `deploy_regression` cleanly.
- **"CoreDNS in CrashLoopBackOff" was classified as `kubernetes`, not `dns`.** Same root cause — generic k8s keywords (`pod`, `crashloopbackoff`) and DNS-specific keywords (`coredns`, `kube-dns`) both scored 2-2 and `kubernetes` won on ordering. The weighted scheme gives `coredns` weight 3 so DNS-flavored alerts now route to the `dns` archetype even when the underlying symptom is a k8s pod restart.

## Mock environment design

- **Original `MockDevOpsEnv` seeded by alert sha, not alert content.** The first version took an `alert_signature` (sha of the alert text) and used it to seed the RNG that picked log templates. That gave deterministic-per-alert outputs but the *content* was random across all archetypes — a "Postgres down" alert often had `query_logs` return Java NullPointerExceptions or Redis pool errors. The agent's investigation trace looked coherent (same query → same result on re-run) but was visibly nonsensical. Fixed by classifying the alert into an archetype on env construction and only sampling log templates from that archetype's pool.
- **`get_metric` was uncorrelated with the alert.** Same issue, different shape — `memory_utilization_percent` returned a value in [85%, 97%] for every alert regardless of whether the alert was about k8s memory pressure or a leaked credential. Fixed by gating elevated metric branches on archetype matches (e.g., memory_utilization is elevated only when archetype is `kubernetes`).
- **`check_pod_status` returned a random unhealthy/healthy mix regardless of alert.** Fixed by setting `unhealthy_likely = archetype in {"kubernetes", "deploy_regression", "latency"}` so pods only break in the archetypes where pod issues are the actual cause.

## Tests

- **`pytest tests/test_agent_loop.py` initially failed because the ReAct loop uses `tool_choice="required"` until the last iteration.** Scripting the assistant's response with `tool_calls=[]` to simulate "text response" hit the `tool_choice="required"` branch first; the model is supposed to return tool_calls. Worked around in the test by always returning a `propose_plan` tool call when termination is needed, which matches real behavior anyway.
- **`tools.classify_alert` keyword "auth" caused false positives on alerts mentioning "Service auth" or "API auth".** Demoted to weight 1 so domain-specific terms (`impossible-travel`, `mfa`, `brute-force`) win. Generic mentions of "auth" no longer override stronger archetypes.

## Evaluation harness

- **`evaluate_planner` threw on refusal rows when expected_runbook was empty.** Original code passed empty string to `retrieval_recall_at_k` and matched against runbook IDs — never matched, so all refusal rows scored 0 on recall@k, polluting the headline metric. Fixed by detecting refusal rows (empty / NaN expected_runbook) and routing them to a separate `refusal_correct` metric instead. The judge call is also skipped on refusal rows since there's no ground-truth runbook to grade against.

## CI

- **GitHub Actions cache wasn't keying on `requirements.txt` for the workflow scope.** Added `cache: pip` on `actions/setup-python` so cold install isn't every run.
- **First CI attempt failed because `pyyaml` wasn't in requirements.txt** — the prompt config loader imports it but I'd been relying on the Jupyter env having it pre-installed. Added to requirements.

## Prompt versioning

- **Refactoring prompts out of source into `prompts/v1.yaml` revealed that the V2 planner's "improved" prompt was hand-coded into `src/planner.py` but never actually used at runtime** — the `prompt_version="baseline"` default in the constructor was hardcoded too, so the improved prompt was dead code. Fixed in the refactor by reading `prompt_version` from the YAML config so both bodies are now reachable through configuration.

---

This file grows whenever something non-obvious bites. The pattern across phases is "smaller-than-it-should-have-been demo data masks design flaws"; the alert-aware tools rewrite forced those flaws into the light.
