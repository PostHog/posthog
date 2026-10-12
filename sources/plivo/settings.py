from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

PLIVO_BASE_URL = "https://api.plivo.com/v1"

# Plivo list endpoints cap `limit` at 20 records per page.
PAGE_SIZE = 20

# Message (MDR) and call (CDR) records are retained for 90 days, and a single list request
# may only span a 30-day time range (Plivo returns a 400 beyond that). Windowed endpoints
# chunk their fetch into <= 30-day slices covering at most the retention window.
RETENTION_DAYS = 90
MAX_QUERY_RANGE_DAYS = 30


@dataclass
class PlivoEndpointConfig:
    name: str
    # Path relative to /v1/Account/{auth_id}/, e.g. "Message/".
    path: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # The record timestamp used for server-side `<field>__gt` / `<field>__lte` filters.
    time_filter_field: str | None = None
    # Stable creation-style timestamp used for datetime partitioning.
    partition_key: str | None = None
    # Response fields parsed from Plivo's timestamp strings into datetimes.
    datetime_fields: tuple[str, ...] = ()
    # Whether requests must be chunked into MAX_QUERY_RANGE_DAYS windows over RETENTION_DAYS.
    windowed: bool = False


PLIVO_ENDPOINTS: dict[str, PlivoEndpointConfig] = {
    "messages": PlivoEndpointConfig(
        name="messages",
        path="Message/",
        primary_keys=["message_uuid"],
        incremental_fields=[incremental_field("message_time")],
        time_filter_field="message_time",
        # message_time is the send/receive time and never changes for a message_uuid.
        partition_key="message_time",
        datetime_fields=("message_time",),
        windowed=True,
    ),
    "calls": PlivoEndpointConfig(
        name="calls",
        path="Call/",
        primary_keys=["call_uuid"],
        incremental_fields=[incremental_field("end_time")],
        time_filter_field="end_time",
        # The call list only returns completed calls, whose end_time is immutable.
        partition_key="end_time",
        datetime_fields=("initiation_time", "answer_time", "end_time"),
        windowed=True,
    ),
    "recordings": PlivoEndpointConfig(
        name="recordings",
        path="Recording/",
        primary_keys=["recording_id"],
        incremental_fields=[incremental_field("add_time")],
        time_filter_field="add_time",
        partition_key="add_time",
        datetime_fields=("add_time",),
        # Recordings are stored until deleted (no 90-day retention), so the first sync must
        # walk the full history rather than a retention-bounded window.
        windowed=False,
    ),
    "applications": PlivoEndpointConfig(
        name="applications",
        path="Application/",
        primary_keys=["app_id"],
        # The application list exposes no server-side time filter — full refresh only.
    ),
}

ENDPOINTS = tuple(PLIVO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PLIVO_ENDPOINTS.items()
}

ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    "messages": (
        "Message detail records (MDRs) for every SMS/MMS sent or received. "
        "Plivo retains messages for 90 days, so the first sync backfills at most that window."
    ),
    "calls": (
        "Call detail records (CDRs) for completed voice calls. "
        "Plivo retains call records for 90 days, so the first sync backfills at most that window."
    ),
    "recordings": "Call and conference recordings stored on your Plivo account.",
    "applications": "Plivo applications that control how calls and messages to your numbers are handled.",
}
