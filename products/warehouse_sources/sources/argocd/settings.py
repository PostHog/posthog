from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField


@frozen
class ArgocdEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    # Stable, immutable field to partition by (creation/deployment timestamps only).
    partition_key: str | None = None
    # Per-application endpoint: `path` carries a `{name}` (and possibly `{revision}`)
    # placeholder and is fetched once per application from the applications list.
    fan_out: bool = False


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
    "application_events": ArgocdEndpointConfig(
        name="application_events",
        path="/api/v1/applications/{name}/events",
        # Event UIDs are unique within the Argo CD control-plane cluster; the parent identity
        # keeps the key unambiguous and makes the table joinable without a lookup.
        primary_keys=["application_namespace", "application_name", "uid"],
        partition_key="created_at",
        fan_out=True,
    ),
    "revision_metadata": ArgocdEndpointConfig(
        name="revision_metadata",
        path="/api/v1/applications/{name}/revisions/{revision}/metadata",
        # One row per revision each application deployed, resolved per source for
        # multi-source applications.
        primary_keys=["application_namespace", "application_name", "revision", "source_index"],
        fan_out=True,
    ),
    "managed_resources": ArgocdEndpointConfig(
        name="managed_resources",
        path="/api/v1/applications/{name}/managed-resources",
        # Managed resources have no id of their own, so the key is the Kubernetes resource
        # identity within the application.
        primary_keys=["application_namespace", "application_name", "group", "kind", "namespace", "name"],
        fan_out=True,
    ),
    "resource_tree": ArgocdEndpointConfig(
        name="resource_tree",
        path="/api/v1/applications/{name}/resource-tree",
        primary_keys=["application_namespace", "application_name", "group", "kind", "namespace", "name"],
        fan_out=True,
    ),
}

ENDPOINTS = tuple(ARGOCD_ENDPOINTS.keys())

# No endpoint exposes a server-side timestamp filter (the applications list has no
# updated-since/created-since param), so nothing is advertised as incremental.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in ARGOCD_ENDPOINTS}
