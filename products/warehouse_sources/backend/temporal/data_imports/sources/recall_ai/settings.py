from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@frozen
class RecallAIEndpointConfig:
    path: str
    # Stable datetime used for Delta partitioning; never an update-tracking column.
    partition_key: str
    # Server-side lower-bound filter param, and the response field it filters on. None
    # means the endpoint has no usable server-side filter and stays full-refresh only.
    incremental_param: str | None = None
    incremental_field: str | None = None
    # Response fields dropped before rows reach the warehouse (credentials the API echoes back).
    scrub_fields: tuple[str, ...] = ()
    extra_params: tuple[tuple[str, str], ...] = ()


RECALL_AI_ENDPOINTS: dict[str, RecallAIEndpointConfig] = {
    # The bot list only filters on join_at (date granularity), and join_at is the scheduled
    # join time: a bot scheduled for next week advances a join_at watermark past bots created
    # later with earlier join times, so rows would be skipped. Full refresh only.
    "bots": RecallAIEndpointConfig(
        path="/api/v1/bot/",
        partition_key="join_at",
        # The bot list paginates by page number unless use_cursor is set; every other list
        # endpoint is cursor-only. Opting in keeps all endpoints on the next-URL paginator.
        extra_params=(("use_cursor", "true"),),
    ),
    "recordings": RecallAIEndpointConfig(
        path="/api/v1/recording/",
        partition_key="created_at",
        incremental_param="created_at_after",
        incremental_field="created_at",
    ),
    "transcripts": RecallAIEndpointConfig(
        path="/api/v1/transcript/",
        partition_key="created_at",
        incremental_param="created_at_after",
        incremental_field="created_at",
    ),
    "participant_events": RecallAIEndpointConfig(
        path="/api/v1/participant_events/",
        partition_key="created_at",
        incremental_param="created_at_after",
        incremental_field="created_at",
    ),
    "meeting_metadata": RecallAIEndpointConfig(
        path="/api/v1/meeting_metadata/",
        partition_key="created_at",
        incremental_param="created_at_after",
        incremental_field="created_at",
    ),
    # Calendars only filter on created_at, which misses status changes on existing rows
    # (connected -> disconnected). The table is small (one row per connected calendar),
    # so full refresh keeps it correct. The API echoes the customer's OAuth app secrets
    # back in list responses; those fields never reach the warehouse.
    "calendars": RecallAIEndpointConfig(
        path="/api/v2/calendars/",
        partition_key="created_at",
        scrub_fields=("oauth_client_secret", "oauth_refresh_token"),
    ),
    "calendar_events": RecallAIEndpointConfig(
        path="/api/v2/calendar-events/",
        partition_key="created_at",
        incremental_param="updated_at__gte",
        incremental_field="updated_at",
    ),
}

ENDPOINTS = tuple(RECALL_AI_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: (
        [
            {
                "label": config.incremental_field,
                "type": IncrementalFieldType.DateTime,
                "field": config.incremental_field,
                "field_type": IncrementalFieldType.DateTime,
            }
        ]
        if config.incremental_param and config.incremental_field
        else []
    )
    for name, config in RECALL_AI_ENDPOINTS.items()
}
