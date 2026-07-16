"""Canonical, documentation-sourced descriptions for Kubecost endpoints and columns.

Sourced from the official Kubecost API reference (https://docs.kubecost.com/apis).
Keyed by the endpoint names in `settings.py` `KUBECOST_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Kubecost table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_ALLOCATION_DOCS_URL = "https://docs.kubecost.com/apis/monitoring-apis/api-allocation"

_ALLOCATION_COLUMNS = {
    "key": "The allocation's name in the queried aggregation (with special entries like __idle__ for unallocated cluster capacity). Unique per window.",
    "window_start": "Start of the one-day query window this row covers (RFC3339). Used as the incremental cursor and partition key.",
    "window_end": "End of the one-day query window this row covers (RFC3339).",
    "name": "The name of the allocation, matching the aggregation level (namespace, controller, or pod).",
    "properties": "Kubernetes metadata for the allocation: cluster, node, namespace, controller, pod, container, labels, and annotations.",
    "window": "The queried time window the allocation was computed over, with start and end timestamps.",
    "start": "Timestamp of the first observed activity for the allocation within the window.",
    "end": "Timestamp of the last observed activity for the allocation within the window.",
    "minutes": "Number of minutes the allocation was running during the window.",
    "cpuCores": "Average number of CPU cores allocated while running.",
    "cpuCoreHours": "Cumulative CPU core-hours allocated over the window.",
    "cpuCost": "Cost of the CPU allocated to the workload over the window.",
    "cpuEfficiency": "Ratio of CPU usage to CPU requested (usage / requested).",
    "gpuCount": "Average number of GPUs allocated while running.",
    "gpuHours": "Cumulative GPU-hours allocated over the window.",
    "gpuCost": "Cost of the GPUs allocated to the workload over the window.",
    "ramBytes": "Average bytes of RAM allocated while running.",
    "ramByteHours": "Cumulative RAM byte-hours allocated over the window.",
    "ramCost": "Cost of the RAM allocated to the workload over the window.",
    "ramEfficiency": "Ratio of RAM usage to RAM requested (usage / requested).",
    "pvBytes": "Average bytes of persistent volume storage allocated while running.",
    "pvCost": "Cost of persistent volume storage allocated to the workload over the window.",
    "networkCost": "Cost of network transfer attributed to the workload over the window.",
    "loadBalancerCost": "Cost of load balancers attributed to the workload over the window.",
    "sharedCost": "Shared costs (e.g. cluster overhead) distributed to the allocation.",
    "externalCost": "Out-of-cluster costs attributed to the allocation via external billing integrations.",
    "totalCost": "Total cumulative cost of the allocation over the window.",
    "totalEfficiency": "Cost-weighted average of CPU and RAM efficiency.",
}


def _allocation_entry(level: str) -> dict:
    return {
        "description": f"Kubernetes workload cost and usage from the Kubecost Allocation API, aggregated by {level} — one row per {level} per day.",
        "docs_url": _ALLOCATION_DOCS_URL,
        "columns": dict(_ALLOCATION_COLUMNS),
    }


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "allocation_by_namespace": _allocation_entry("namespace"),
    "allocation_by_controller": _allocation_entry("controller"),
    "allocation_by_pod": _allocation_entry("pod"),
    "assets": {
        "description": "Cluster infrastructure costs from the Kubecost Assets API — one row per asset (node, disk, network, load balancer, cluster management fee) per day.",
        "docs_url": "https://docs.kubecost.com/apis/monitoring-apis/assets-api",
        "columns": {
            "key": "The asset's fully qualified identifier (provider/account/service/cluster/type/…). Unique per window.",
            "window_start": "Start of the one-day query window this row covers (RFC3339). Used as the incremental cursor and partition key.",
            "window_end": "End of the one-day query window this row covers (RFC3339).",
            "type": "The asset type: Node, Disk, Network, LoadBalancer, ClusterManagement, or Cloud.",
            "properties": "Asset metadata: cloud provider, account, project, service, cluster, and name.",
            "labels": "Kubernetes and cloud provider labels attached to the asset.",
            "window": "The queried time window the asset cost was computed over, with start and end timestamps.",
            "start": "Timestamp of the first observed activity for the asset within the window.",
            "end": "Timestamp of the last observed activity for the asset within the window.",
            "minutes": "Number of minutes the asset was running during the window.",
            "cpuCores": "Number of CPU cores on the asset (nodes).",
            "cpuCoreHours": "Cumulative CPU core-hours provided by the asset over the window.",
            "cpuCost": "Cost of the asset's CPU over the window.",
            "gpuCost": "Cost of the asset's GPUs over the window.",
            "ramBytes": "Bytes of RAM on the asset (nodes).",
            "ramByteHours": "Cumulative RAM byte-hours provided by the asset over the window.",
            "ramCost": "Cost of the asset's RAM over the window.",
            "discount": "Percentage discount applied to the asset's cost (e.g. negotiated or sustained-use discounts).",
            "preemptible": "Whether the node is a preemptible/spot instance (nodes).",
            "adjustment": "Cost adjustment applied during reconciliation with cloud-billing data.",
            "totalCost": "Total cumulative cost of the asset over the window.",
        },
    },
}
