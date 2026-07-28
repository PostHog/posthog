"""Canonical, documentation-sourced descriptions for CAST AI endpoints and columns.

Sourced from the official CAST AI API reference (https://api.cast.ai/v1/spec). Keyed by the
resource names in `settings.py` `CASTAI_ENDPOINTS`, which match the `ExternalDataSchema.name` of
a synced CAST AI table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Cost fields shared by both the cluster-level and per-workload cost breakdowns.
_COST_BREAKDOWN_COLUMNS = {
    "costOnDemand": "Average hourly cost of on-demand instances for the given time bucket.",
    "costSpot": "Average hourly cost of spot instances for the given time bucket.",
    "costSpotFallback": "Average hourly cost of spot-fallback instances for the given time bucket.",
    "cpuCountOnDemand": "Average number of CPUs on on-demand instances for the given time bucket.",
    "cpuCountSpot": "Average number of CPUs on spot instances for the given time bucket.",
    "cpuCountSpotFallback": "Average number of CPUs on spot-fallback instances for the given time bucket.",
    "cpuCostOnDemand": "Average hourly CPU cost of on-demand instances for the given time bucket.",
    "cpuCostSpot": "Average hourly CPU cost of spot instances for the given time bucket.",
    "cpuCostSpotFallback": "Average hourly CPU cost of spot-fallback instances for the given time bucket.",
    "ramCostOnDemand": "Average hourly RAM cost of on-demand instances for the given time bucket.",
    "ramCostSpot": "Average hourly RAM cost of spot instances for the given time bucket.",
    "ramCostSpotFallback": "Average hourly RAM cost of spot-fallback instances for the given time bucket.",
    "ramGibOnDemand": "Average number of RAM GiB on on-demand instances for the given time bucket.",
    "ramGibSpot": "Average number of RAM GiB on spot instances for the given time bucket.",
    "ramGibSpotFallback": "Average number of RAM GiB on spot-fallback instances for the given time bucket.",
    "gpuCostOnDemand": "Average hourly GPU cost of on-demand instances for the given time bucket.",
    "gpuCostSpot": "Average hourly GPU cost of spot instances for the given time bucket.",
    "gpuCostSpotFallback": "Average hourly GPU cost of spot-fallback instances for the given time bucket.",
    "gpuCountOnDemand": "Average number of GPUs on on-demand instances for the given time bucket.",
    "gpuCountSpot": "Average number of GPUs on spot instances for the given time bucket.",
    "gpuCountSpotFallback": "Average number of GPUs on spot-fallback instances for the given time bucket.",
    "storageGib": "Average number of provisioned storage GiB for the given time bucket.",
    "storageCost": "Average hourly storage cost for the given time bucket.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "clusters": {
        "description": "A Kubernetes cluster connected to CAST AI for cost monitoring and optimization.",
        "docs_url": "https://docs.cast.ai/docs/cluster-management",
        "columns": {
            "id": "Unique identifier of the cluster.",
            "name": "Name of the cluster.",
            "organizationId": "Identifier of the CAST AI organization the cluster belongs to.",
            "credentialsId": "Identifier of the cloud credentials used to manage the cluster.",
            "createdAt": "Time at which the cluster was registered with CAST AI.",
            "region": "Cloud provider region the cluster runs in.",
            "status": "Onboarding/connection status of the cluster (e.g. ready, disconnected).",
            "agentSnapshotReceivedAt": "Time the CAST AI agent last reported cluster state.",
            "agentStatus": "Health status of the CAST AI agent running in the cluster.",
            "providerType": "Cloud provider the cluster runs on (e.g. eks, gke, aks).",
            "deletedAt": "Time at which the cluster was disconnected/deleted, if applicable.",
            "kubernetesVersion": "Version of Kubernetes the cluster is running.",
            "managedBy": "How the cluster's nodes are managed (e.g. CAST AI, Karpenter).",
        },
    },
    "cluster_cost_reports": {
        "description": (
            "Historical compute cost for a cluster, bucketed by time interval and broken down "
            "by on-demand, spot, and spot-fallback instance cost."
        ),
        "docs_url": "https://docs.cast.ai/docs/cost-reports",
        "columns": {
            "cluster_id": "Identifier of the cluster this cost entry belongs to.",
            "timestamp": "Start of the time bucket this cost entry covers.",
            "totalCpuCostOnDemand": "Total on-demand CPU cost for the time bucket.",
            "totalRamCostOnDemand": "Total on-demand RAM cost for the time bucket.",
            "totalGpuCostOnDemand": "Total on-demand GPU cost for the time bucket.",
            "totalStorageCost": "Total storage cost for the time bucket.",
            **_COST_BREAKDOWN_COLUMNS,
        },
    },
    "cluster_savings_history": {
        "description": (
            "Historical comparison of a cluster's real cost against CAST AI's estimated optimal "
            "cost under different optimization strategies, used to track realized and available savings."
        ),
        "docs_url": "https://docs.cast.ai/docs/cost-reports",
        "columns": {
            "cluster_id": "Identifier of the cluster this savings entry belongs to.",
            "createdAt": "Time this savings snapshot was recorded.",
            "current": "Cluster's actual cost as currently configured.",
            "optimizedSpotInstances": "Estimated cost if fully optimized using spot instances.",
            "optimizedLayman": "Estimated cost under CAST AI's balanced (non-spot) optimization strategy.",
            "optimizedSpotOnly": "Estimated cost under a spot-only optimization strategy.",
        },
    },
}
