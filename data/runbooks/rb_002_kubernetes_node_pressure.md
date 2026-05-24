# Runbook: Kubernetes Node Memory Pressure / Pod Evictions

**Category:** infra
**Severity:** SEV-2
**Tags:** kubernetes, k8s, memory, evictions, autoscaling

## Symptoms
- `kubectl get events` shows repeated `Evicted` events with reason `MemoryPressure`.
- Node condition `MemoryPressure=True` on one or more nodes.
- Pods restarting with `OOMKilled` even when the container limit was not breached.

## Triage Steps
1. Identify the affected nodes: `kubectl get nodes -o jsonpath='{range .items[?(@.status.conditions[?(@.type=="MemoryPressure")].status=="True")]}{.metadata.name}{"\n"}{end}'`.
2. List the top memory-consuming pods on each affected node: `kubectl top pod --all-namespaces --sort-by=memory`.
3. Check whether a deploy or HPA scale event in the last 30 minutes coincides with the pressure onset.
4. Confirm cluster-autoscaler is healthy and not blocked (look for `pod didn't trigger scale-up` warnings).

## Mitigation
1. Cordon the affected node(s) to prevent new scheduling: `kubectl cordon <node>`.
2. Drain low-priority workloads first: `kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --pod-selector='priority!=critical'`.
3. If autoscaler is healthy, deletion of the node will trigger a replacement.
4. If autoscaler is blocked, manually increase the node-group desired count by one in the cloud console.

## Validation
- `MemoryPressure` condition clears on the original node within 10 minutes.
- No new `Evicted` events in the cluster for 15 minutes.
- HPA metrics show pod count stable at or near the target replicas.

## Post-incident
- Review per-pod requests vs. actuals for the affected workloads; raise requests for the worst offenders.
- If the trigger was a deploy, add a memory-regression check to the CI pipeline.
