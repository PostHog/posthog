from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class DeepgramEndpointConfig:
    name: str
    # Path suffix appended to /v1/projects/{project_id} for the per-project fan-out endpoints.
    # Empty string is the top-level /v1/projects list itself (see `is_project_list`).
    path: str
    # Key in the JSON response body that holds the list of rows (Deepgram wraps every list in an
    # envelope, e.g. {"projects": [...]}, {"requests": [...]}).
    data_key: str
    primary_keys: list[str]
    # Stable creation-time field used for datetime partitioning. Never a mutable field.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    supports_incremental: bool = False
    # page/limit pagination — only the requests log supports it; the other endpoints return a full
    # unpaginated array.
    paginated: bool = False
    # The top-level /v1/projects list. It seeds the fan-out and is not itself fanned out per project.
    is_project_list: bool = False
    # Sub-object to lift into the row root before keying/partitioning (e.g. /keys nests the key under
    # "api_key"). None means the row is used as-is.
    flatten_key: Optional[str] = None
    should_sync_default: bool = True


DEEPGRAM_ENDPOINTS: dict[str, DeepgramEndpointConfig] = {
    "projects": DeepgramEndpointConfig(
        name="projects",
        path="",
        data_key="projects",
        primary_keys=["project_id"],
        is_project_list=True,
    ),
    "members": DeepgramEndpointConfig(
        name="members",
        path="/members",
        data_key="members",
        # member_id is only unique within a project, so key on the pair to stay unique table-wide.
        primary_keys=["project_id", "member_id"],
    ),
    "keys": DeepgramEndpointConfig(
        name="keys",
        path="/keys",
        data_key="api_keys",
        primary_keys=["project_id", "api_key_id"],
        partition_key="created",
        flatten_key="api_key",
    ),
    "balances": DeepgramEndpointConfig(
        name="balances",
        path="/balances",
        data_key="balances",
        primary_keys=["project_id", "balance_id"],
    ),
    "invites": DeepgramEndpointConfig(
        name="invites",
        path="/invites",
        data_key="invites",
        # Invites have no id; the invited email is unique per project.
        primary_keys=["project_id", "email"],
    ),
    # The request log is the highest-value stream: one row per inference request with model/feature
    # metadata, response code, and a `created` timestamp. It is the only endpoint with a genuine
    # server-side timestamp filter (`start`/`end` on `created`) and page/limit pagination, so it is
    # the only one synced incrementally.
    "requests": DeepgramEndpointConfig(
        name="requests",
        path="/requests",
        data_key="requests",
        primary_keys=["project_id", "request_id"],
        partition_key="created",
        supports_incremental=True,
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
