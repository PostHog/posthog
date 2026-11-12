from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

FATHOM_BASE_URL = "https://api.fathom.ai/external/v1"

_CREATED_AT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "created_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass(frozen=True)
class FathomEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    params: dict[str, Any] = field(default_factory=dict)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # `created_at` is set once when the item is created, so it is a stable partition key.
    partition_key: Optional[str] = None
    # When set, each row keeps only these keys. Summaries and transcripts come from the same
    # `/meetings` list as `meetings`, so they keep only the key, the timestamp and their own payload.
    columns: Optional[tuple[str, ...]] = None


# The page size is fixed by Fathom (10 meetings per page), so no endpoint sends a limit.
FATHOM_ENDPOINTS: dict[str, FathomEndpointConfig] = {
    "meetings": FathomEndpointConfig(
        name="meetings",
        path="/meetings",
        primary_keys=["recording_id"],
        # Fathom counts `include_summary` and `include_transcript` as heavy requests with a lower
        # rate limit. These three flags are not heavy, and their payloads are small.
        params={
            "include_action_items": "true",
            "include_crm_matches": "true",
            "include_highlights": "true",
        },
        incremental_fields=_CREATED_AT_INCREMENTAL_FIELDS,
        partition_key="created_at",
    ),
    "meeting_summaries": FathomEndpointConfig(
        name="meeting_summaries",
        path="/meetings",
        primary_keys=["recording_id"],
        params={"include_summary": "true"},
        incremental_fields=_CREATED_AT_INCREMENTAL_FIELDS,
        partition_key="created_at",
        columns=("recording_id", "created_at", "default_summary"),
    ),
    "meeting_transcripts": FathomEndpointConfig(
        name="meeting_transcripts",
        path="/meetings",
        primary_keys=["recording_id"],
        params={"include_transcript": "true"},
        incremental_fields=_CREATED_AT_INCREMENTAL_FIELDS,
        partition_key="created_at",
        columns=("recording_id", "created_at", "transcript_language", "transcript"),
    ),
    # Teams and meeting types have no id; Fathom keys them by name within an organization.
    "meeting_types": FathomEndpointConfig(
        name="meeting_types",
        path="/meeting_types",
        primary_keys=["name"],
    ),
    "teams": FathomEndpointConfig(
        name="teams",
        path="/teams",
        primary_keys=["name"],
    ),
    "team_members": FathomEndpointConfig(
        name="team_members",
        path="/team_members",
        primary_keys=["email"],
    ),
    # Only an API key of an account admin can read this endpoint. Other keys get a 403.
    "users": FathomEndpointConfig(
        name="users",
        path="/users",
        primary_keys=["email"],
    ),
}

ENDPOINTS = tuple(FATHOM_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FATHOM_ENDPOINTS.items() if config.incremental_fields
}
