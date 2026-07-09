from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class DeepgramEndpointConfig:
    name: str
    path: str  # Template with a {project_id} placeholder for project-scoped endpoints
    response_key: str  # Key in the response JSON holding the list of rows
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_key: str | None = None  # Stable datetime field for partitioning (created-style, never updated)
    fan_out_over_projects: bool = True  # All Deepgram data except /projects is project-scoped
    paginated: bool = False  # Only /requests supports page/limit pagination


DEEPGRAM_ENDPOINTS: dict[str, DeepgramEndpointConfig] = {
    "projects": DeepgramEndpointConfig(
        name="projects",
        path="/projects",
        response_key="projects",
        primary_keys=["project_id"],
        fan_out_over_projects=False,
    ),
    "api_keys": DeepgramEndpointConfig(
        name="api_keys",
        path="/projects/{project_id}/keys",
        response_key="api_keys",
        primary_keys=["project_id", "api_key_id"],
    ),
    "members": DeepgramEndpointConfig(
        name="members",
        path="/projects/{project_id}/members",
        response_key="members",
        primary_keys=["project_id", "member_id"],
    ),
    "balances": DeepgramEndpointConfig(
        name="balances",
        path="/projects/{project_id}/balances",
        response_key="balances",
        primary_keys=["project_id", "balance_id"],
    ),
    "requests": DeepgramEndpointConfig(
        name="requests",
        path="/projects/{project_id}/requests",
        response_key="requests",
        primary_keys=["project_id", "request_id"],
        partition_key="created",
        paginated=True,
        incremental_fields=[
            {
                "label": "created",
                "type": IncrementalFieldType.DateTime,
                "field": "created",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
}

ENDPOINTS = tuple(DEEPGRAM_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DEEPGRAM_ENDPOINTS.items()
}
