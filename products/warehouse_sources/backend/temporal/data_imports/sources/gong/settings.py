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
    primary_key: str
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
