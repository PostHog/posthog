from posthog.dataclasses import frozen


@frozen
class OptimizelyEndpointConfig:
    path: str
    # Most v2 list endpoints are project-scoped and need a project_id param,
    # so the transport fans out over the projects list.
    project_scoped: bool = True
    primary_key: str = "id"
    # Per-entity endpoints (results, timeseries) take one parent row's id in the path, so the
    # transport walks projects -> parent list -> this endpoint, one request per parent row.
    parent: str | None = None
    parent_id_param: str | None = None


# Optimizely's v2 list endpoints have no updated-since filters, and all the
# entities are low-volume experiment configuration, so every stream is an
# honest full refresh. Raw event-level data only exists in the separate S3
# Enriched Events Export, which is out of scope for a REST connector.
OPTIMIZELY_ENDPOINTS: dict[str, OptimizelyEndpointConfig] = {
    "projects": OptimizelyEndpointConfig(
        path="/projects",
        project_scoped=False,
    ),
    "experiments": OptimizelyEndpointConfig(
        path="/experiments",
    ),
    "audiences": OptimizelyEndpointConfig(
        path="/audiences",
    ),
    "events": OptimizelyEndpointConfig(
        path="/events",
    ),
    "pages": OptimizelyEndpointConfig(
        path="/pages",
    ),
    "campaigns": OptimizelyEndpointConfig(
        path="/campaigns",
    ),
    "attributes": OptimizelyEndpointConfig(
        path="/attributes",
    ),
    # Results are a point-in-time computation over the experiment's (or campaign's) whole run, with
    # no change cursor, so they are full refresh too: each sync replaces the snapshot per parent.
    "experiment_results": OptimizelyEndpointConfig(
        path="/experiments/{experiment_id}/results",
        primary_key="experiment_id",
        parent="experiments",
        parent_id_param="experiment_id",
    ),
    "experiment_timeseries": OptimizelyEndpointConfig(
        path="/experiments/{experiment_id}/timeseries",
        primary_key="experiment_id",
        parent="experiments",
        parent_id_param="experiment_id",
    ),
    "campaign_results": OptimizelyEndpointConfig(
        path="/campaigns/{campaign_id}/results",
        primary_key="campaign_id",
        parent="campaigns",
        parent_id_param="campaign_id",
    ),
}

ENDPOINTS = tuple(OPTIMIZELY_ENDPOINTS.keys())
