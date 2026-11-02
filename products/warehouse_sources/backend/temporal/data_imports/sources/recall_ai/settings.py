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
    # A dotted path drops a key inside a nested object.
    scrub_fields: tuple[str, ...] = ()
    extra_params: tuple[tuple[str, str], ...] = ()
    # False for endpoints that return a bare JSON array instead of a cursor-paginated envelope.
    paginated: bool = True
    incremental_field_type: IncrementalFieldType = IncrementalFieldType.DateTime


USAGE_ENDPOINT = "usage"
# The usage endpoint allows 5 requests per minute per workspace.
USAGE_REQUEST_INTERVAL_SECONDS = 12.0
USAGE_BACKFILL_DAYS = 90
USAGE_RESTATEMENT_DAYS = 3

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
    # The list takes only a cursor, and upload status changes after creation, so full refresh.
    # upload_token authorizes uploads into the workspace and never reaches the warehouse.
    "desktop_sdk_uploads": RecallAIEndpointConfig(
        path="/api/v1/sdk_upload/",
        partition_key="created_at",
        scrub_fields=("upload_token",),
    ),
    # Unpaginated and unfiltered, and status changes after creation, so full refresh. The
    # nested platform credentials (Zoom RTMS signature, Google Meet access token) are dropped.
    "meeting_direct_connects": RecallAIEndpointConfig(
        path="/api/v1/meeting_direct_connect/",
        partition_key="created_at",
        scrub_fields=("zoom_rtms.signature", "google_meet_media_api.access_token"),
        paginated=False,
    ),
    # One row per UTC day, built from one request per day. The endpoint only returns a bot_total
    # for the requested range, so `date` and `bot_total` are the whole row. Recent days restate
    # as late bot completions are billed, so incremental syncs re-read a trailing window.
    USAGE_ENDPOINT: RecallAIEndpointConfig(
        path="/api/v1/billing/usage/",
        partition_key="date",
        incremental_param="start",
        incremental_field="date",
        paginated=False,
        incremental_field_type=IncrementalFieldType.Date,
    ),
}

ENDPOINTS = tuple(RECALL_AI_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: (
        [
            {
                "label": config.incremental_field,
                "type": config.incremental_field_type,
                "field": config.incremental_field,
                "field_type": config.incremental_field_type,
            }
        ]
        if config.incremental_param and config.incremental_field
        else []
    )
    for name, config in RECALL_AI_ENDPOINTS.items()
}
