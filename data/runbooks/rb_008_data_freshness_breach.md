# Runbook: Data Freshness SLA Breach

**Category:** data
**Severity:** SEV-2
**Tags:** freshness, sla, dashboard, streaming

## Symptoms
- A monitored table's `max(updated_at)` is older than the freshness SLA threshold.
- Real-time dashboards show "last update X hours ago" where X exceeds the contract.
- Consumers of the data report stale values via support tickets.

## Triage Steps
1. Identify the immediate upstream of the affected table. Is the failure at ingestion (Kafka / CDC) or at transformation (dbt / batch job)?
2. If the upstream is a stream, check the consumer-lag metric on the Kafka topic / Kinesis stream.
3. If the upstream is a batch, check the orchestrator's last successful run for the dependency chain.
4. Confirm whether the failure is for ALL partitions or only a subset (sometimes a single tenant's data is delayed).

## Mitigation
1. **Streaming lag:** scale up the consumer group, or open the bottleneck (slow downstream sink, partition skew).
2. **Batch backlog:** trigger a manual catch-up run with appropriate concurrency limits to avoid overwhelming the warehouse.
3. **Partial failure:** isolate the failing partition / tenant and run a targeted backfill for that slice only.
4. While catching up, post a notice on the data catalog entry so consumers know the staleness window.

## Validation
- `max(updated_at)` returns to within the SLA threshold.
- Consumer-lag on the relevant stream is near zero.
- Stakeholders confirm dashboards are current.

## Post-incident
- Add a freshness-check alarm with a lower threshold so the next breach is caught earlier.
- If the root cause was partition skew, open a follow-up to reshard.
