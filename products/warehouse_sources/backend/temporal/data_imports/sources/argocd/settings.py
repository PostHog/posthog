from dataclasses import dataclass

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class ArgocdEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    # Stable, immutable field to partition by (creation/deployment timestamps only).
    partition_key: str | None = None


# Argo CD's list APIs return the whole collection in one Kubernetes-style List response
# (`{"items": [...]}`). There is no reliable pagination and no server-side timestamp
# filter on any of them, so every endpoint is full refresh.
ARGOCD_ENDPOINTS: dict[str, ArgocdEndpointConfig] = {
    "applications": ArgocdEndpointConfig(
        name="applications",
        path="/api/v1/applications",
        # With apps-in-any-namespace enabled, application names are only unique per namespace.
        primary_keys=["namespace", "name"],
        partition_key="created_at",
    ),
    "deployment_history": ArgocdEndpointConfig(
        name="deployment_history",
        # Flattened from each application's `status.history` — Argo CD has no standalone
        # deployment-history API.
        path="/api/v1/applications",
        # History ids increment per application, so the key needs the parent identity.
        primary_keys=["application_namespace", "application_name", "id"],
        partition_key="deployed_at",
    ),
    "projects": ArgocdEndpointConfig(
        name="projects",
        path="/api/v1/projects",
        # AppProjects are cluster-scoped in Argo CD, so the name is unique.
        primary_keys=["name"],
        partition_key="created_at",
    ),
    "repositories": ArgocdEndpointConfig(
        name="repositories",
        path="/api/v1/repositories",
        primary_keys=["repo"],
    ),
    "clusters": ArgocdEndpointConfig(
        name="clusters",
        path="/api/v1/clusters",
        primary_keys=["server"],
    ),
}

ENDPOINTS = tuple(ARGOCD_ENDPOINTS.keys())

# No endpoint exposes a server-side timestamp filter (the applications list has no
# updated-since/created-since param), so nothing is advertised as incremental.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in ARGOCD_ENDPOINTS}
