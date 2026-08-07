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

# Report rows carry the conversation's own creation timestamp (the report's date
# filter is anchored on it), so that column is the incremental cursor.
_REPORT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "created_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]

# Report streams request one date window at a time, oldest first, so the cursor
# advances monotonically and a retried sync resumes at the last finished window.
REPORT_WINDOW_DAYS = 7
# How far back the first sync of a report stream reaches. Export jobs only retain
# 14 days, but reports can be generated for any past window, so this is a cost
# bound (number of report requests), not a vendor limit.
REPORT_BACKFILL_DAYS = 730
# Report rows restate as records change (e.g. a conversation closes after its row
# was first synced), so incremental runs re-read a trailing window; merge on the
# primary key dedupes the overlap. Older rows only refresh on a full refresh.
REPORT_INCREMENTAL_LOOKBACK_SECONDS = 30 * 24 * 60 * 60


@dataclass
class GladlyEndpointConfig:
    name: str
    # Filename inside each export job (e.g. customers.jsonl) for job-export streams.
    filename: str | None = None
    # Metric set generated via POST /api/v1/reports for report streams.
    report_metric_set: str | None = None
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
    "conversations": GladlyEndpointConfig(
        name="conversations",
        report_metric_set="ConversationExportReport",
        primary_key="conversation_id",
        incremental_fields=list(_REPORT_INCREMENTAL_FIELDS),
    ),
}

ENDPOINTS = tuple(GLADLY_ENDPOINTS.keys())

# Report rows restate in place (status, closed timestamps), so appending would
# duplicate conversations — these streams only support incremental merge.
REPORT_ENDPOINTS = tuple(name for name, config in GLADLY_ENDPOINTS.items() if config.report_metric_set)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GLADLY_ENDPOINTS.items() if config.incremental_fields
}
