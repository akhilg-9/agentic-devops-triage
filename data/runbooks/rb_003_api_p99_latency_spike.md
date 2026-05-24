# Runbook: API p99 Latency Spike

**Category:** app
**Severity:** SEV-2
**Tags:** latency, api, performance, slo

## Symptoms
- p99 latency on the public API exceeds 2× baseline for more than 5 minutes.
- Error rate may or may not be elevated; pure latency regressions often have a normal 2xx rate.
- Customer-facing dashboards show "slow" without explicit failures.

## Triage Steps
1. Open the API latency dashboard. Determine whether the spike is uniform across endpoints or concentrated in one route.
2. Cross-reference with deploy history — was anything shipped in the last 60 minutes?
3. Check downstream dependency latency (database, cache, third-party APIs). A 50 ms spike upstream often surfaces as a 500 ms spike downstream once retries pile up.
4. Inspect tail-latency tracing for the slowest 1% of requests; identify the dominant span.

## Mitigation
1. If a recent deploy is the trigger, roll back the deployment via the standard rollback playbook.
2. If a single downstream is slow, enable circuit breakers for that dependency to fail fast rather than queueing.
3. If the cache hit rate has collapsed, warm the cache from the most recent known-good snapshot.
4. Consider rate-limiting noisy abusive clients identified in the per-client latency view.

## Validation
- p99 returns to within 20% of baseline for at least 10 consecutive minutes.
- No alert pages for the same SLO in the next hour.

## Post-incident
- Add a tracing-based check for the specific span that dominated the spike.
- If rollback was used, file the root-cause investigation as a blocking ticket on the next attempt.
