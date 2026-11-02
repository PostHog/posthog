from dataclasses import field
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@frozen
class GongEndpointConfig:
    name: str
    path: str
    # Key under which the records array lives in the JSON response (e.g. "calls", "users").
    response_key: str
    # A tuple names a composite key, for rows unique only per user and day.
    primary_key: str | tuple[str, ...]
    # Stable datetime field to partition by (never `updated`/`lastModified`). None disables partitioning.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Only `True` when Gong exposes a genuine server-side timestamp filter for the endpoint.
    supports_incremental: bool = False
    # `/v2/calls` requires `fromDateTime` and caps each request to a 90-day range, so it is
    # synced by iterating bounded date windows rather than a single cursor scan.
    uses_date_window: bool = False
    # `/v2/calls/extensive` is a POST endpoint whose filter, content selector, and pagination
    # cursor live in a JSON body, and whose rows wrap the call fields in a `metaData` object
    # alongside the enrichment blocks the content selector asked for. Requires the broader
    # `api:calls:read:extensive` scope.
    uses_extensive: bool = False
    # `contentSelector` sent to `/v2/calls/extensive`. Gong omits every enrichment block that is
    # not explicitly requested here, so this decides which sibling keys of `metaData` come back.
    extensive_content_selector: Optional[dict[str, Any]] = None
    # Sibling keys of `metaData` to keep as nested columns on the flattened row. Must line up with
    # what `extensive_content_selector` requests, or the columns arrive permanently null.
    extensive_row_keys: tuple[str, ...] = ()
    # `POST /v2/calls/transcript` answers with `callId` and `transcript` and nothing else. Endpoints
    # that set this are driven off the `/v2/calls` list for the same window instead: each page of
    # calls supplies the `callIds` filter for one transcript request, and the call's `started`
    # stamps the rows that come back.
    uses_call_id_batches: bool = False
    # Keys of the inclusive start and exclusive end `YYYY-MM-DD` bounds in the JSON `filter` of the
    # `/v2/stats/...` POST endpoints. Gong reads these dates in the company's time zone. Endpoints
    # that set this send whole-day windows instead of `fromDateTime`/`toDateTime`.
    date_filter_keys: Optional[tuple[str, str]] = None
    # Filter fields sent with every request alongside the date bounds.
    extra_filter: dict[str, Any] = field(default_factory=dict)
    # Days per request window. Stats endpoints aggregate over the whole window, so a one-day window
    # gives one row per user per day. None keeps the 90-day cap that `/v2/calls` enforces.
    window_days: Optional[int] = None
    # Column that receives the window's start date, for endpoints whose rows carry no date of their own.
    window_date_column: Optional[str] = None
    # Key of the list nested in each record that holds the actual rows, for endpoints that return one
    # record per user with that user's days inside it. Each nested item becomes a row that also carries
    # the record's other fields.
    nested_rows_key: Optional[str] = None
    # Endpoint whose rows drive one request each, for endpoints that list what belongs to one parent.
    fan_out_parent: Optional[str] = None
    # Field of each parent row that is sent as the `fan_out_param` query parameter.
    fan_out_parent_field: str = "id"
    fan_out_param: Optional[str] = None
    # Parent field that must be truthy for the parent to drive a request, e.g. `active` on users.
    fan_out_parent_filter: Optional[str] = None
    # Column that receives the parent field on each row, for rows that do not name their parent.
    fan_out_column: Optional[str] = None
    # Whether the same row comes back for many parents and is kept only once per sync.
    dedupe_fan_out_rows: bool = False
    # Whether a 404 such as "No folders found" means there is nothing to sync rather than an error.
    not_found_is_empty: bool = False
    # Whether responses from this endpoint may be sampled into HTTP troubleshooting storage.
    # Disabled for endpoints whose bodies carry participant names, free-form CRM field values, or
    # verbatim conversation text that the name-based scrubbers can't recognise; requests stay
    # metered and logged.
    capture_http_samples: bool = True
    # Trailing window each incremental run re-reads, for endpoints whose rows can appear well after
    # the timestamp they sort by. None leaves the schema on the platform default.
    default_incremental_lookback_seconds: Optional[int] = None
    # Rows-per-chunk override for endpoints whose rows are whole documents. None keeps the
    # pipeline's default.
    chunk_size: Optional[int] = None
    # Whether one-shot source setup and new-schema auto-sync enable this endpoint without the
    # administrator picking it. False for endpoints carrying content sensitive enough that syncing
    # it into the warehouse should be a deliberate choice.
    should_sync_default: bool = True


GONG_ENDPOINTS: dict[str, GongEndpointConfig] = {
    "calls": GongEndpointConfig(
        name="calls",
        path="/v2/calls",
        response_key="calls",
        primary_key="id",
        partition_key="started",
        supports_incremental=True,
        uses_date_window=True,
        incremental_fields=[
            {
                "label": "started",
                "type": IncrementalFieldType.DateTime,
                "field": "started",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # Same call universe as `calls`, but sourced from `POST /v2/calls/extensive` so each row
    # additionally carries `parties` (participant name/email/affiliation) and CRM `context`
    # (linked Salesforce/HubSpot objects and fields) — neither of which the basic `/v2/calls`
    # list can return. Kept as a separate table so enabling it never changes the `calls` schema.
    "calls_extensive": GongEndpointConfig(
        name="calls_extensive",
        path="/v2/calls/extensive",
        response_key="calls",
        primary_key="id",
        partition_key="started",
        supports_incremental=True,
        uses_date_window=True,
        uses_extensive=True,
        capture_http_samples=False,
        extensive_content_selector={
            "context": "Extended",
            "exposedFields": {"parties": True},
        },
        extensive_row_keys=("parties", "context"),
        incremental_fields=[
            {
                "label": "started",
                "type": IncrementalFieldType.DateTime,
                "field": "started",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # Gong's Call Spotlight summaries, from the same `/v2/calls/extensive` endpoint under the same
    # scope as `calls_extensive` but with the `content` block of the selector requested instead of
    # participants and CRM links. Kept as its own default-off table because a call's AI-generated
    # summary is far more sensitive than the metadata in the other call tables: syncing it puts
    # what was said on every call in reach of anyone who can query the warehouse, so it takes a
    # deliberate pick rather than arriving with the rest of the source.
    "calls_content": GongEndpointConfig(
        name="calls_content",
        path="/v2/calls/extensive",
        response_key="calls",
        primary_key="id",
        partition_key="started",
        supports_incremental=True,
        uses_date_window=True,
        uses_extensive=True,
        capture_http_samples=False,
        should_sync_default=False,
        extensive_content_selector={
            # No CRM context or participants — `calls_extensive` already covers those, and asking
            # for them again would double the payload for data this table does not expose.
            "context": "None",
            "exposedFields": {
                "content": {
                    "brief": True,
                    "keyPoints": True,
                    "highlights": True,
                    "callOutcome": True,
                    "outline": True,
                }
            },
        },
        extensive_row_keys=("content",),
        incremental_fields=[
            {
                "label": "started",
                "type": IncrementalFieldType.DateTime,
                "field": "started",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # Transcript text for the same calls, from `POST /v2/calls/transcript`, which returns only
    # `callId` and `transcript`. Each row is stamped with the `started` of the call it belongs to,
    # read from the `/v2/calls` page that drove the request — without it a transcript carries no
    # date to sync incrementally on, partition by, or filter a query with.
    # Requires the `api:calls:read:transcript` scope on top of `api:calls:read:basic`.
    "transcripts": GongEndpointConfig(
        name="transcripts",
        path="/v2/calls/transcript",
        response_key="callTranscripts",
        primary_key="callId",
        partition_key="started",
        supports_incremental=True,
        uses_date_window=True,
        uses_call_id_batches=True,
        capture_http_samples=False,
        # Gong transcribes asynchronously, so a call synced before its transcript finished
        # processing would otherwise sit below the watermark forever. Re-read the last week.
        default_incremental_lookback_seconds=7 * 24 * 60 * 60,
        # A row is a whole call transcript, so flush far fewer of them per Arrow table.
        chunk_size=500,
        incremental_fields=[
            {
                "label": "started",
                "type": IncrementalFieldType.DateTime,
                "field": "started",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "users": GongEndpointConfig(
        name="users",
        path="/v2/users",
        response_key="users",
        primary_key="id",
        partition_key="created",
    ),
    "scorecards": GongEndpointConfig(
        name="scorecards",
        path="/v2/settings/scorecards",
        response_key="scorecards",
        primary_key="scorecardId",
        partition_key="created",
    ),
    # Keyword trackers (the phrases Gong listens for on calls) across every workspace. Gong returns
    # them in one unpaginated response. AI trackers are not included.
    # Requires the `api:settings:trackers:read` scope.
    "trackers": GongEndpointConfig(
        name="trackers",
        path="/v2/settings/trackers",
        response_key="keywordTrackers",
        primary_key="trackerId",
        partition_key="created",
    ),
    # Answers to the scorecards in `scorecards`, one row per review of a call. Filtered by review
    # date, so a call reviewed long after it took place still arrives on the next run. Default-off
    # because reviewers' free-text feedback on a rep's call is performance-review data.
    # Requires the `api:stats:scorecards` scope.
    "answered_scorecards": GongEndpointConfig(
        name="answered_scorecards",
        path="/v2/stats/activity/scorecards",
        response_key="answeredScorecards",
        primary_key="answeredScorecardId",
        partition_key="callStartTime",
        supports_incremental=True,
        uses_date_window=True,
        date_filter_keys=("reviewFromDate", "reviewToDate"),
        # Gong defaults to manual reviews only.
        extra_filter={"reviewMethod": "BOTH"},
        capture_http_samples=False,
        should_sync_default=False,
        incremental_fields=[
            {
                "label": "reviewTime",
                "type": IncrementalFieldType.DateTime,
                "field": "reviewTime",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # Per-user conversation metrics (talk ratio, longest monologue, patience, ...) for each day,
    # requested one day at a time because Gong aggregates over the whole requested range.
    # Requires the `api:stats:interaction` scope.
    "interaction_stats": GongEndpointConfig(
        name="interaction_stats",
        path="/v2/stats/interaction",
        response_key="peopleInteractionStats",
        primary_key=("userId", "day"),
        partition_key="day",
        supports_incremental=True,
        uses_date_window=True,
        date_filter_keys=("fromDate", "toDate"),
        window_days=1,
        window_date_column="day",
        # A day's stats change as Gong finishes processing that day's calls. Re-read the last week.
        default_incremental_lookback_seconds=7 * 24 * 60 * 60,
        incremental_fields=[
            {
                "label": "day",
                "type": IncrementalFieldType.Date,
                "field": "day",
                "field_type": IncrementalFieldType.Date,
            },
        ],
    ),
    # Per-user activity for each day: the ids of the calls the user hosted, attended, listened to,
    # shared, commented on, gave feedback on, and scored. Gong returns one record per user with the
    # days nested inside, and only for users with activity in the range.
    # Requires the `api:stats:user-actions:detailed` scope.
    "daily_activity": GongEndpointConfig(
        name="daily_activity",
        path="/v2/stats/activity/day-by-day",
        response_key="usersDetailedActivities",
        nested_rows_key="userDailyActivityStats",
        primary_key=("userId", "fromDate"),
        partition_key="fromDate",
        supports_incremental=True,
        uses_date_window=True,
        date_filter_keys=("fromDate", "toDate"),
        # A day's activity can still change after the day ends, as Gong finishes processing its calls.
        default_incremental_lookback_seconds=7 * 24 * 60 * 60,
        incremental_fields=[
            {
                "label": "fromDate",
                "type": IncrementalFieldType.DateTime,
                "field": "fromDate",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # The call outcome values (e.g. "Connected", "No Answer") defined for the company.
    # Requires the `api:call-outcomes:read` scope.
    "call_outcomes": GongEndpointConfig(
        name="call_outcomes",
        path="/v2/call-outcomes",
        response_key="outcomes",
        primary_key="callOutcome",
    ),
    # Public call library folders. Gong does not return private or archived folders.
    # Requires the `api:library:read` scope.
    "library_folders": GongEndpointConfig(
        name="library_folders",
        path="/v2/library/folders",
        response_key="folders",
        primary_key="id",
        not_found_is_empty=True,
    ),
    # The calls and call snippets in each public library folder, requested one folder at a time.
    # The same call can sit in a folder more than once as different snippets, so the time it was
    # added is part of the key. Notes are free text that the sample scrubbers can't recognise.
    # Requires the `api:library:read` scope.
    "library_folder_calls": GongEndpointConfig(
        name="library_folder_calls",
        path="/v2/library/folder-content",
        response_key="calls",
        primary_key=("folderId", "id", "created"),
        partition_key="created",
        fan_out_parent="library_folders",
        fan_out_param="folderId",
        fan_out_column="folderId",
        not_found_is_empty=True,
        capture_http_samples=False,
    ),
    # Gong Engage flows. Gong lists company flows plus the personal and shared flows of one owner per
    # request, so every active user is asked for in turn and each flow is kept once.
    # Requires the `api:flows:read` scope.
    "flows": GongEndpointConfig(
        name="flows",
        path="/v2/flows",
        response_key="flows",
        primary_key="id",
        fan_out_parent="users",
        fan_out_parent_field="emailAddress",
        fan_out_param="flowOwnerEmail",
        fan_out_parent_filter="active",
        dedupe_fan_out_rows=True,
    ),
    "workspaces": GongEndpointConfig(
        name="workspaces",
        path="/v2/workspaces",
        response_key="workspaces",
        primary_key="id",
    ),
}

ENDPOINTS = tuple(GONG_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GONG_ENDPOINTS.items()
}
