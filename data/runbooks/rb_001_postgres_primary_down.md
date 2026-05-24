# Runbook: Postgres Primary Database Down

**Category:** infra
**Severity:** SEV-1
**Tags:** postgres, database, replication, failover

## Symptoms
- Application logs show `connection refused` to the primary Postgres host.
- `pg_isready` against the primary returns exit code 2.
- Read-replicas are still reachable but writes are failing across services.

## Triage Steps
1. Confirm the primary is unreachable from at least two distinct network locations (bastion + app subnet) to rule out a network partition.
2. Check the cloud provider status page for the database region.
3. Inspect the most recent `postgresql.log` lines via the managed-DB console for OOM, disk-full, or replication conflicts.
4. Verify the replica lag on each standby with `SELECT now() - pg_last_xact_replay_timestamp();` — a small lag is safe to promote, a large lag means data loss on failover.

## Mitigation
1. If lag on the freshest standby is < 5 seconds, promote it: `SELECT pg_promote();` on the standby, then update the writer DNS record / connection-pool config.
2. Drain the old primary from the connection pool to prevent split-brain.
3. Re-point applications by rolling the connection-pooler pods (PgBouncer / RDS Proxy) — do not require a full app deploy.
4. If lag is too large, escalate to the DBA on-call before promoting; consider read-only mode while recovering the primary.

## Validation
- `pg_isready` against the new primary returns 0.
- Synthetic write transaction completes in < 1 second.
- Replication is re-established to at least one standby within 30 minutes.

## Post-incident
- File a timeline document with the trigger, detection latency, and time-to-mitigate.
- Open a ticket to rebuild the demoted primary as a fresh standby.
