from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.komodor.settings import API_DOCS_URL

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "services": {
        "description": "Kubernetes services with their health status, latest deployment, and latest issue.",
        "docs_url": f"{API_DOCS_URL}#/Services/post_api_v2_services_search",
        "columns": {
            "cluster": "Cluster identifier.",
            "namespace": "Namespace that contains the service.",
            "service": "Service name.",
            "kind": "Service kind.",
            "uid": "Unique service identifier.",
            "status": "Service health status.",
            "lastDeploy": "Latest deployment details.",
            "lastIssue": "Latest issue details.",
        },
    },
    "jobs": {
        "description": "Kubernetes jobs and cron jobs with their status and issue details.",
        "docs_url": f"{API_DOCS_URL}#/Jobs/post_api_v2_jobs_search",
        "columns": {
            "cluster": "Cluster identifier.",
            "namespace": "Namespace that contains the job.",
            "name": "Job name.",
            "kind": "Job kind.",
            "uid": "Unique job identifier.",
            "status": "Job status.",
            "startTime": "Job start time as a Unix timestamp.",
        },
    },
    "clusters": {
        "description": "Kubernetes clusters connected to Komodor.",
        "docs_url": f"{API_DOCS_URL}#/Clusters/get_api_v2_clusters",
        "columns": {
            "name": "Cluster name.",
            "clusterId": "Local cluster identifier.",
            "tags": "Tags associated with the cluster.",
            "apiServerUrl": "Cluster API server URL.",
        },
    },
    "monitors": {
        "description": "Monitor configurations used to detect failures in Kubernetes infrastructure.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "id": "Monitor identifier.",
            "name": "Monitor name.",
            "type": "Monitor type.",
            "active": "Whether the monitor is active.",
            "createdAt": "Time when the monitor configuration was created.",
            "updatedAt": "Time when the monitor configuration was updated.",
            "createdFrom": "Application that created the configuration.",
        },
    },
}
