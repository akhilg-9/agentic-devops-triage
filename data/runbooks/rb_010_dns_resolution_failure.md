# Runbook: Internal DNS Resolution Failure

**Category:** infra
**Severity:** SEV-1 (often blast-radius is the whole cluster)
**Tags:** dns, coredns, networking, kubernetes

## Symptoms
- Pods log `lookup ... : no such host` or `Temporary failure in name resolution`.
- Service-to-service calls within the cluster fail intermittently.
- External name resolution from inside the cluster also fails.

## Triage Steps
1. Confirm the failure is DNS, not a downstream outage: `dig @<cluster-dns-ip> kubernetes.default.svc.cluster.local` from a debug pod.
2. Check CoreDNS / kube-dns pod health: `kubectl -n kube-system get pods -l k8s-app=kube-dns`. Look for `CrashLoopBackOff` or restart counts.
3. Inspect CoreDNS logs for upstream-resolver errors — the cluster DNS forwards external names to a resolver, which may itself be down.
4. Check if a recent change (NetworkPolicy, CoreDNS configmap edit, upstream resolver swap) coincides with the issue.

## Mitigation
1. **CoreDNS pod failure:** scale CoreDNS replicas up (`kubectl scale -n kube-system deploy/coredns --replicas=N+2`) to absorb load while debugging.
2. **Configmap regression:** revert the CoreDNS Corefile configmap to the previous version; restart CoreDNS pods to pick up the change.
3. **Upstream resolver down:** swap the upstream in the Corefile to a known-good resolver (e.g., 8.8.8.8) temporarily until the in-house resolver recovers.
4. **NetworkPolicy regression:** identify and rollback the offending policy. DNS requires UDP/TCP 53 to CoreDNS from all pods.

## Validation
- DNS lookups from a sample of pods succeed for both internal and external names.
- Service-to-service error rate returns to baseline.

## Post-incident
- Add a probe that runs a periodic in-cluster DNS lookup and alerts on failure rate, independent of CoreDNS pod health.
- If the change was via the Corefile, gate future edits behind a staged rollout.
