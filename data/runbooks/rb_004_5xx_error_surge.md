# Runbook: 5xx Error Rate Surge

**Category:** app
**Severity:** SEV-1 if > 5% of traffic, SEV-2 otherwise
**Tags:** errors, api, 5xx, deploy

## Symptoms
- HTTP 500/502/503/504 rate exceeds 1% on the public ingress.
- Error budget burn alert fires.
- Customer reports of "failures" or "white screen" pile up in support.

## Triage Steps
1. Break down the 5xx by status code:
   - 500 = usually app-internal exceptions, check application logs.
   - 502 / 504 = upstream timeout or bad-gateway, check load balancer and the service it fronts.
   - 503 = capacity or health-check failure, check pod readiness and autoscaler events.
2. Pull the top 5 stack traces from structured logs in the affected window.
3. Compare error-rate by version label — is one deploy revision responsible?
4. Check for a config-change event in the last hour (feature flags, secrets rotation, DNS edits).

## Mitigation
1. If a single deploy revision owns >80% of the errors, roll back to the previous revision.
2. If a feature flag was flipped, revert it via the feature-flag console (no deploy needed).
3. If errors are concentrated on one downstream, enable a graceful degradation path (cached fallback, 200 with empty payload, etc.).
4. Scale up the affected service by 50% temporarily if the root cause is capacity.

## Validation
- 5xx rate returns below 0.5% for at least 15 minutes.
- Top stack traces from the incident no longer appear in logs.

## Post-incident
- Write an RCA. Always identify why the issue was not caught in staging.
- Add a regression test that would have caught the failing change.
