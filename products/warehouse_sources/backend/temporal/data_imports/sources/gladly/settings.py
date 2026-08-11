from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Rows don't carry an export timestamp themselves, so the transport injects the
# producing job's updatedAt — that injected field is the incremental cursor.
_JOB_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "_job_updated_at",
        "type": IncrementalFieldType.DateTime,
        "field": "_job_updated_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]

# Timestamps-report rows carry the event's own recorded time (the report's date
# filter is anchored on it), so that column is the incremental cursor.
_TIMESTAMPS_REPORT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "timestamp",
        "type": IncrementalFieldType.DateTime,
        "field": "timestamp",
        "field_type": IncrementalFieldType.DateTime,
    },
]

# Conversation-report rows carry the conversation's own creation timestamp (the
# report's date filter is anchored on it), so that column is the incremental cursor.
_REPORT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "created_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]

# Injected primary key for report streams whose rows have no natural unique id
# (event-grain reports ship no event id column): a deterministic hash of the
# whole normalized row. The transport injects it when an endpoint declares it
# as the primary key.
REPORT_ROW_ID_COLUMN = "_row_id"

# Conversation-report rows restate as records change (e.g. a conversation closes
# after its row was first synced), so incremental runs re-read a trailing window;
# merge on the primary key dedupes the overlap. Older rows only refresh on a full
# refresh.
REPORT_INCREMENTAL_LOOKBACK_SECONDS = 30 * 24 * 60 * 60


@dataclass
class GladlyEndpointConfig:
    name: str
    # Filename inside each export job (e.g. customers.jsonl) for job-export streams.
    filename: str | None = None
    # Metric set generated via POST /api/v1/reports for report streams.
    report_metric_set: str | None = None
    # Report streams request one date window at a time, oldest first. Event-grain
    # reports default to 1-day windows to stay clear of Gladly's 100k-row report
    # cap, which truncates silently.
    report_window_days: int = 1
    # How far back the first sync of a report stream reaches. Reports can be
    # generated for any past window, so this is a cost bound (the reports
    # endpoint allows 10 requests per minute per org), not a vendor limit.
    report_backfill_days: int = 90
    # Default-off in the schema picker; used for high-volume event-grain tables
    # so enabling them is an explicit choice.
    should_sync_default: bool = True
    primary_key: str = "id"
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(_JOB_INCREMENTAL_FIELDS))


# Gladly has no list-all REST surface — bulk data ships as JSONL files inside
# vendor-scheduled export jobs (hourly/daily, 14-day retention). Every stream
# maps to one file per job; jobs are processed oldest-first so the watermark
# advances monotonically, and merge-on-id dedupes records that appear in
# multiple exports.
GLADLY_ENDPOINTS: dict[str, GladlyEndpointConfig] = {
    "customers": GladlyEndpointConfig(
        name="customers",
        filename="customers.jsonl",
    ),
    "conversation_items": GladlyEndpointConfig(
        name="conversation_items",
        filename="conversation_items.jsonl",
    ),
    "agents": GladlyEndpointConfig(
        name="agents",
        filename="agents.jsonl",
    ),
    "topics": GladlyEndpointConfig(
        name="topics",
        filename="topics.jsonl",
    ),
    # Export jobs ship no conversations file and the REST API only lists
    # conversations per customer, so conversation-level rows come from the
    # Conversation Export report (one row per conversation, anchored on its
    # creation date). Column names are the report's CSV headers, snake_cased.
    # One row per conversation keeps 7-day windows clear of the row cap, and
    # the 730-day backfill is a cost bound, not a vendor limit.
    "conversations": GladlyEndpointConfig(
        name="conversations",
        report_metric_set="ConversationExportReport",
        primary_key="conversation_id",
        report_window_days=7,
        report_backfill_days=730,
        incremental_fields=list(_REPORT_INCREMENTAL_FIELDS),
    ),
    # Handle-time, first-response, and wait-time analytics need Gladly's
    # purpose-built timestamps reports — export jobs ship no equivalent files.
    # Both reports are event-grain (one row per conversation/contact event)
    # with no natural row id, so the transport injects a deterministic
    # full-row hash as the primary key. Column names are the report's CSV
    # headers, snake_cased.
    "conversation_timestamps": GladlyEndpointConfig(
        name="conversation_timestamps",
        report_metric_set="ConversationTimestampsReport",
        primary_key=REPORT_ROW_ID_COLUMN,
        should_sync_default=False,
        incremental_fields=list(_TIMESTAMPS_REPORT_INCREMENTAL_FIELDS),
    ),
    "contact_timestamps": GladlyEndpointConfig(
        name="contact_timestamps",
        report_metric_set="ContactTimestampsReport",
        primary_key=REPORT_ROW_ID_COLUMN,
        should_sync_default=False,
        incremental_fields=list(_TIMESTAMPS_REPORT_INCREMENTAL_FIELDS),
    ),
}

ENDPOINTS = tuple(GLADLY_ENDPOINTS.keys())

# Report windows are re-read on resume and behind the incremental watermark, and
# conversation rows restate in place (status, closed timestamps), so appending
# would duplicate rows — these streams only support incremental merge.
REPORT_ENDPOINTS = tuple(name for name, config in GLADLY_ENDPOINTS.items() if config.report_metric_set)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GLADLY_ENDPOINTS.items() if config.incremental_fields
}

SHOULD_SYNC_DEFAULT: dict[str, bool] = {name: config.should_sync_default for name, config in GLADLY_ENDPOINTS.items()}
