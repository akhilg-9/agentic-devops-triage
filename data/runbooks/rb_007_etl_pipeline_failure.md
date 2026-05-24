# Runbook: Nightly ETL Pipeline Failure

**Category:** data
**Severity:** SEV-2
**Tags:** etl, airflow, dbt, data-quality

## Symptoms
- The orchestrator (Airflow / Dagster / Prefect) reports a failed DAG run for the nightly load.
- Downstream dashboards show "stale data" or missing today's partition.
- dbt test failures appear in the post-load step.

## Triage Steps
1. Open the failed task's logs. Categorize the failure:
   - Source-system unavailable (upstream API / DB down).
   - Schema drift (a column was added / removed / renamed upstream).
   - Data-quality test failure (referential integrity, freshness, uniqueness).
   - Resource failure (out-of-memory, disk full on the warehouse).
2. Check whether the upstream source is healthy and whether yesterday's run succeeded.
3. Diff the source schema against the warehouse contract.

## Mitigation
1. **Source unavailable:** wait and retry the failed task; if upstream is down for hours, mark the run as skipped and flag the freshness SLA in the data catalog.
2. **Schema drift:** open an emergency PR adjusting the model to tolerate the new schema; coordinate with the upstream owner before merging.
3. **Data-quality failure:** quarantine the load (do not promote to production tables), open a ticket for the data-owning team, and surface the issue on the catalog.
4. **Resource failure:** scale the warehouse temporarily or split the offending job into smaller chunks.

## Validation
- The DAG completes successfully on retry.
- Dashboards reflect today's partition.
- dbt tests pass in the post-load step.

## Post-incident
- Add an upstream-schema contract test that would have caught the drift earlier.
- If the failure was repeated, raise the SLO on the source pipeline and notify the upstream team.
