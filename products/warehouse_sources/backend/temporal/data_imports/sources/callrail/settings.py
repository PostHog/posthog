from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class CallRailEndpointConfig:
    name: str
    # Path under the account-scoped base (https://api.callrail.com/v3/a/{account_id}).
    path: str
    # Key the list lives under in the JSON envelope, e.g. {"calls": [...], "total_pages": N}.
    response_key: str
    incremental_fields: list[IncrementalField]
    # Stable datetime field used for datetime partitioning. Only set where we are confident the
    # field is present on every row (never `updated_at` / `last_*` — those rewrite partitions).
    partition_key: Optional[str] = None
    # Field passed to the API's `sort=` param (ascending) and, for incremental endpoints, the field
    # the `start_date` server-side filter narrows on. Required when supports_incremental is True so
    # rows arrive in ascending cursor order and the watermark advances correctly.
    sort_field: Optional[str] = None
    # True only where CallRail exposes a genuine server-side date filter (`start_date`) on this
    # resource. Everything else is full refresh.
    supports_incremental: bool = False
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True


# CallRail v3 REST API. All data endpoints are nested under /v3/a/{account_id}/.
#
# Incremental support is set only for resources whose list endpoint documents a server-side
# `start_date` date filter that narrows on a stable timestamp (Calls -> start_time,
# Form submissions -> submitted_at). For those we advertise exactly that one field as the
# incremental cursor so the cursor, the `sort=` field, and the `start_date` filter all agree.
# The remaining resources are mutable configuration objects or lack a usable server-side date
# filter, so they ship full refresh only.
CALLRAIL_ENDPOINTS: dict[str, CallRailEndpointConfig] = {
    "calls": CallRailEndpointConfig(
        name="calls",
        path="/calls.json",
        response_key="calls",
        partition_key="start_time",
        sort_field="start_time",
        supports_incremental=True,
        incremental_fields=[
            {
                "label": "start_time",
                "type": IncrementalFieldType.DateTime,
                "field": "start_time",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "companies": CallRailEndpointConfig(
        name="companies",
        path="/companies.json",
        response_key="companies",
        partition_key="created_at",
        incremental_fields=[],
    ),
    "form_submissions": CallRailEndpointConfig(
        name="form_submissions",
        path="/form_submissions.json",
        response_key="form_submissions",
        partition_key="submitted_at",
        sort_field="submitted_at",
        supports_incremental=True,
        incremental_fields=[
            {
                "label": "submitted_at",
                "type": IncrementalFieldType.DateTime,
                "field": "submitted_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "text_messages": CallRailEndpointConfig(
        name="text_messages",
        # Returns SMS conversations under the "conversations" key.
        path="/text-messages.json",
        response_key="conversations",
        incremental_fields=[],
    ),
    "trackers": CallRailEndpointConfig(
        name="trackers",
        path="/trackers.json",
        response_key="trackers",
        incremental_fields=[],
    ),
    "users": CallRailEndpointConfig(
        name="users",
        path="/users.json",
        response_key="users",
        incremental_fields=[],
    ),
    "tags": CallRailEndpointConfig(
        name="tags",
        path="/tags.json",
        response_key="tags",
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(CALLRAIL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CALLRAIL_ENDPOINTS.items()
}
