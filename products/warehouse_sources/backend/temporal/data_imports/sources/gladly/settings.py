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

# The work session report windows a row on its contact's end time, or on the
# creation time while the contact is open. Ending only moves a row to a later
# window, so the creation time is a safe incremental cursor.
_WORK_SESSION_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "contact_session_created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "contact_session_created_at",
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

# After-contact and unknown time keep accumulating on a work session after its
# contact ends, until the next contact begins or the conversation closes.
WORK_SESSION_INCREMENTAL_LOOKBACK_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class GladlyEndpointConfig:
    name: str
    # Filename inside each export job (e.g. customers.jsonl) for job-export streams.
    filename: str | None = None
    # Path of a non-paginated JSON array endpoint for lookup streams.
    list_path: str | None = None
    # Metric set generated via POST /api/v1/reports for report streams.
    report_metric_set: str | None = None
    # Some metric sets only accept a time range (startAtTime/endAtTime), not a
    # date range (startAt/endAt).
    report_uses_time_range: bool = False
    # Columns that together identify a row when the report has no usable id. The
    # injected `_row_id` then hashes only these, so a restated row merges onto its
    # earlier version. Left empty, it hashes the whole row.
    report_row_id_columns: tuple[str, ...] = ()
    # Rows with this column blank are provisional and are skipped. They come back
    # in a later window once the column is filled in.
    report_final_row_column: str | None = None
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
    default_incremental_lookback_seconds: int | None = None


# Gladly has no paginated list-all REST surface — bulk data ships as JSONL files inside
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
        default_incremental_lookback_seconds=REPORT_INCREMENTAL_LOOKBACK_SECONDS,
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
    # One row per contact and agent who worked it, from the work session report
    # (the WorkSessionEventsReportV4 metric set returns the same data as
    # POST /api/v1/reports/work-session-events). The report's `id` column is
    # blank until the contact ends and was not unique before late 2022, so the
    # key is built from contact_session_id + agent_id, the pair Gladly documents
    # as unique. agent_id is blank for a contact no agent has handled. It is also
    # blank while a contact is open, so open contacts are skipped: their row key
    # would never match the row the contact gets once it ends. An ended contact
    # moves to the window of its end time, so a later sync picks it up.
    "work_session_events": GladlyEndpointConfig(
        name="work_session_events",
        report_metric_set="WorkSessionEventsReportV4",
        report_uses_time_range=True,
        report_row_id_columns=("contact_session_id", "agent_id"),
        report_final_row_column="contact_session_ended_at",
        primary_key=REPORT_ROW_ID_COLUMN,
        should_sync_default=False,
        incremental_fields=list(_WORK_SESSION_INCREMENTAL_FIELDS),
        default_incremental_lookback_seconds=WORK_SESSION_INCREMENTAL_LOOKBACK_SECONDS,
    ),
    # Small lookups that resolve the team and inbox ids on other tables. Both
    # return the whole collection unpaginated with no change filter, so they
    # only full-refresh.
    "teams": GladlyEndpointConfig(
        name="teams",
        list_path="/teams",
        incremental_fields=[],
    ),
    "inboxes": GladlyEndpointConfig(
        name="inboxes",
        list_path="/inboxes",
        incremental_fields=[],
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

INCREMENTAL_LOOKBACK_SECONDS: dict[str, int] = {
    name: config.default_incremental_lookback_seconds
    for name, config in GLADLY_ENDPOINTS.items()
    if config.default_incremental_lookback_seconds is not None
}
