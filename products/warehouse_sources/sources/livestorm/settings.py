from typing import Optional

from products.warehouse_sources.sources.sdk import (
    DependentEndpointConfig,
    IncrementalField,
    IncrementalFieldType,
    frozen,
)

LIVESTORM_BASE_URL = "https://api.livestorm.co/v1"

# Livestorm caps `page[size]` at 50.
PAGE_SIZE = 50

# Livestorm sends timestamps as Unix seconds, and `filter[updated_since]` accepts the same.
UPDATED_AT_INCREMENTAL_FIELD: IncrementalField = {
    "label": "updated_at",
    "type": IncrementalFieldType.DateTime,
    "field": "updated_at",
    "field_type": IncrementalFieldType.Integer,
}


@frozen
class LivestormEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField]
    default_incremental_field: Optional[str] = None
    page_size: int = PAGE_SIZE
    fanout: Optional[DependentEndpointConfig] = None


SESSION_FANOUT = DependentEndpointConfig(
    parent_name="sessions",
    resolve_param="session_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "session_id"},
)

LIVESTORM_ENDPOINTS: dict[str, LivestormEndpointConfig] = {
    "events": LivestormEndpointConfig(
        name="events",
        path="/events",
        primary_keys=["id"],
        incremental_fields=[UPDATED_AT_INCREMENTAL_FIELD],
        default_incremental_field="updated_at",
    ),
    "sessions": LivestormEndpointConfig(
        name="sessions",
        path="/sessions",
        primary_keys=["id"],
        incremental_fields=[UPDATED_AT_INCREMENTAL_FIELD],
        default_incremental_field="updated_at",
    ),
    # `/people` takes no date filter, so it is full refresh only.
    "people": LivestormEndpointConfig(
        name="people",
        path="/people",
        primary_keys=["id"],
        incremental_fields=[],
    ),
    "session_people": LivestormEndpointConfig(
        name="session_people",
        path="/sessions/{session_id}/people",
        primary_keys=["session_id", "id"],
        incremental_fields=[UPDATED_AT_INCREMENTAL_FIELD],
        default_incremental_field="updated_at",
        fanout=SESSION_FANOUT,
    ),
    "session_chat_messages": LivestormEndpointConfig(
        name="session_chat_messages",
        path="/sessions/{session_id}/chat_messages",
        primary_keys=["session_id", "id"],
        incremental_fields=[],
        fanout=SESSION_FANOUT,
    ),
    "session_questions": LivestormEndpointConfig(
        name="session_questions",
        path="/sessions/{session_id}/questions",
        primary_keys=["session_id", "id"],
        incremental_fields=[],
        fanout=SESSION_FANOUT,
    ),
    "team_members": LivestormEndpointConfig(
        name="team_members",
        path="/users",
        primary_keys=["id"],
        incremental_fields=[],
    ),
    "people_attributes": LivestormEndpointConfig(
        name="people_attributes",
        path="/people_attributes",
        primary_keys=["id"],
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(LIVESTORM_ENDPOINTS.keys())
ADMIN_READ_ENDPOINTS = ("team_members", "people_attributes")
OPT_IN_ENDPOINTS = ("session_chat_messages", "session_questions", *ADMIN_READ_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: list(config.incremental_fields) for name, config in LIVESTORM_ENDPOINTS.items() if config.incremental_fields
}
