from dataclasses import dataclass


@dataclass
class OptimizelyEndpointConfig:
    path: str
    # Most v2 list endpoints are project-scoped and need a project_id param,
    # so the transport fans out over the projects list.
    project_scoped: bool = True
    primary_key: str = "id"


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
}

ENDPOINTS = tuple(OPTIMIZELY_ENDPOINTS.keys())
