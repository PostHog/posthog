from dataclasses import dataclass
from typing import Literal, Optional

PaginationStyle = Literal["cursor", "offset"]


@dataclass
class PipedriveEndpointConfig:
    name: str
    path: str
    # v2 endpoints use cursor pagination; v1 endpoints use start/limit offset pagination.
    pagination: PaginationStyle
    primary_key: str = "id"
    # Stable creation-time field used for datetime partitioning. Never an update_time-style
    # field, which would rewrite partitions on every sync. `None` disables partitioning for
    # endpoints (users, *_fields) whose rows have no stable creation timestamp.
    partition_key: Optional[str] = "add_time"


# Endpoints whose path and pagination are identical across every supported source version.
# Their v1 collection endpoints have no v2 replacement (notes, leads, users, *_fields) or were
# already on v2 (deals, persons, organizations, products, pipelines, stages), so they don't
# change between our `v1` and `v2` labels.
_SHARED_ENDPOINTS: dict[str, PipedriveEndpointConfig] = {
    "deals": PipedriveEndpointConfig(name="deals", path="/api/v2/deals", pagination="cursor"),
    "persons": PipedriveEndpointConfig(name="persons", path="/api/v2/persons", pagination="cursor"),
    "organizations": PipedriveEndpointConfig(name="organizations", path="/api/v2/organizations", pagination="cursor"),
    "products": PipedriveEndpointConfig(name="products", path="/api/v2/products", pagination="cursor"),
    "pipelines": PipedriveEndpointConfig(name="pipelines", path="/api/v2/pipelines", pagination="cursor"),
    "stages": PipedriveEndpointConfig(name="stages", path="/api/v2/stages", pagination="cursor"),
    "notes": PipedriveEndpointConfig(name="notes", path="/api/v1/notes", pagination="offset"),
    "leads": PipedriveEndpointConfig(name="leads", path="/api/v1/leads", pagination="offset"),
    "users": PipedriveEndpointConfig(name="users", path="/api/v1/users", pagination="offset", partition_key=None),
    "deal_fields": PipedriveEndpointConfig(
        name="deal_fields", path="/api/v1/dealFields", pagination="offset", partition_key=None
    ),
    "person_fields": PipedriveEndpointConfig(
        name="person_fields", path="/api/v1/personFields", pagination="offset", partition_key=None
    ),
    "organization_fields": PipedriveEndpointConfig(
        name="organization_fields", path="/api/v1/organizationFields", pagination="offset", partition_key=None
    ),
}

# `activities` is the only endpoint that differs by version: Pipedrive deprecated the v1
# offset endpoint in favour of the v2 cursor endpoint (same `id`/`add_time` fields).
_ACTIVITIES_BY_VERSION: dict[str, PipedriveEndpointConfig] = {
    "v1": PipedriveEndpointConfig(name="activities", path="/api/v1/activities", pagination="offset"),
    "v2": PipedriveEndpointConfig(name="activities", path="/api/v2/activities", pagination="cursor"),
}


def endpoints_for_version(api_version: str) -> dict[str, PipedriveEndpointConfig]:
    """Endpoint configs for a resolved source version. Only a deliberate `v1` pin uses the
    deprecated offset `activities` endpoint; every other label (the default `v2`, or a pin we
    don't recognise) uses the current v2 cursor endpoint rather than the sunset one."""
    activities = _ACTIVITIES_BY_VERSION["v1"] if api_version == "v1" else _ACTIVITIES_BY_VERSION["v2"]
    return {**_SHARED_ENDPOINTS, "activities": activities}


# Endpoint names are version-independent (`activities` exists under both), so schema discovery
# can enumerate them without a resolved version.
ENDPOINTS = (*_SHARED_ENDPOINTS.keys(), "activities")
