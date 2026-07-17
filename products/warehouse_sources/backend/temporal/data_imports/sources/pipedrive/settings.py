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


PIPEDRIVE_ENDPOINTS: dict[str, PipedriveEndpointConfig] = {
    "deals": PipedriveEndpointConfig(name="deals", path="/api/v2/deals", pagination="cursor"),
    "persons": PipedriveEndpointConfig(name="persons", path="/api/v2/persons", pagination="cursor"),
    "organizations": PipedriveEndpointConfig(name="organizations", path="/api/v2/organizations", pagination="cursor"),
    "products": PipedriveEndpointConfig(name="products", path="/api/v2/products", pagination="cursor"),
    "pipelines": PipedriveEndpointConfig(name="pipelines", path="/api/v2/pipelines", pagination="cursor"),
    "stages": PipedriveEndpointConfig(name="stages", path="/api/v2/stages", pagination="cursor"),
    "activities": PipedriveEndpointConfig(name="activities", path="/api/v1/activities", pagination="offset"),
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

ENDPOINTS = tuple(PIPEDRIVE_ENDPOINTS.keys())
