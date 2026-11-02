from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

USERSNAP_BASE_URL = "https://platform.usersnap.com/v0.1"
# Feedback list pages accept limit 1-100 (default 10).
PAGE_SIZE = 100


@dataclass
class UsersnapEndpointConfig:
    name: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning. Never an updated_at-style
    # field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None


# The Usersnap REST API (v0.1) exposes projects and per-project feedback items. Only the
# feedbacks/filter endpoint supports a server-side timestamp filter (`filter_type: created_at`
# with gte), so `feedbacks` is the only incremental table; `updated_at` is orderable but not
# filterable, so changes to existing feedback items are only picked up on a full refresh.
USERSNAP_ENDPOINTS: dict[str, UsersnapEndpointConfig] = {
    "projects": UsersnapEndpointConfig(
        name="projects",
        primary_keys=["project_id"],
    ),
    "feedbacks": UsersnapEndpointConfig(
        name="feedbacks",
        primary_keys=["feedback_id"],
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "project_assignees": UsersnapEndpointConfig(
        name="project_assignees",
        # user_id is only unique per project (the same user can be an assignee on many
        # projects), so the fan-out key must include the parent project.
        primary_keys=["project_id", "user_id"],
    ),
}

ENDPOINTS = tuple(USERSNAP_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in USERSNAP_ENDPOINTS.items() if config.incremental_fields
}
