# Runbook: Disk Full on a Production Host or Volume

**Category:** infra
**Severity:** SEV-2 (SEV-1 if it is a database)
**Tags:** disk, storage, ebs, logs

## Symptoms
- `df -h` shows 95%+ utilization on a critical mount.
- Application logs report "no space left on device" or write failures.
- Cloud-provider alarm for `VolumeDiskUsage` fires.

## Triage Steps
1. Identify the largest consumers on the affected mount: `du -h --max-depth=2 /var | sort -h | tail -20`.
2. Determine whether the growth is due to:
   - Application logs not being rotated.
   - Core dumps or crash artifacts.
   - Database WAL / temp files (do NOT delete these without DBA review).
   - Container image cache (`/var/lib/docker`, `/var/lib/containerd`).
3. Check the rate of fill. If the volume is filling at multi-GB/min, treat as imminent SEV-1.

## Mitigation
1. **Safe deletes:** rotate logs (`logrotate --force`), clear `/tmp` items older than 24h, prune container image caches (`docker system prune -af` on hosts under load only with caution).
2. **Database hosts:** never delete WAL or data files manually. Add storage (online resize for cloud volumes), then investigate the source of the bloat after pressure is relieved.
3. **Online volume resize:** for EBS / persistent disks, expand the volume and then grow the filesystem (`resize2fs` or `xfs_growfs`) — verify the kernel sees the new size first with `lsblk`.
4. If the host runs a stateful workload and is unrecoverable, fail traffic over to a peer and rebuild the affected host.

## Validation
- Mount utilization drops below 80%.
- Application writes succeed.
- No further "no space left on device" errors for 30 minutes.

## Post-incident
- Raise the alarm threshold to warn at 75% so future fills are caught earlier.
- Add log-rotation if it was missing.
