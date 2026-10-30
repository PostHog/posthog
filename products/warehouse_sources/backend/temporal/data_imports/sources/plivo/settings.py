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

MULTI_PARTY_CALLS = "multi_party_calls"
MULTI_PARTY_CALL_PARTICIPANTS = "multi_party_call_participants"
USAGE_SUMMARY = "usage_summary"

# UsageSummary pages with a cursor and accepts up to 1000 rows per page. With `day` granularity a
# single request may span at most 92 days, so the backfill is chunked into windows of that size.
USAGE_PAGE_SIZE = 1000
USAGE_MAX_QUERY_RANGE_DAYS = 92
USAGE_BACKFILL_DAYS = 365
# Usage figures, not dimensions: a restated day keeps its row id so merge updates it in place.
USAGE_METRIC_FIELDS = frozenset({"total_units", "duration_seconds", "total_amount", "surcharge"})


@dataclass(frozen=True)
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
    # Response path of the grand total that ends offset pagination. Listings whose `meta.count`
    # meaning is undocumented set None and stop on a short page instead.
    total_path: str | None = "meta.total_count"


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
    "numbers": PlivoEndpointConfig(
        name="numbers",
        # Rented numbers. `PhoneNumber/` is the search for numbers available to buy, not this list.
        path="Number/",
        primary_keys=["number"],
        # The number list only filters by renewal_date, which changes on every renewal — full refresh only.
    ),
    MULTI_PARTY_CALLS: PlivoEndpointConfig(
        name=MULTI_PARTY_CALLS,
        path="MultiPartyCall/",
        primary_keys=["mpc_uuid"],
        incremental_fields=[incremental_field("end_time")],
        time_filter_field="end_time",
        partition_key="creation_time",
        datetime_fields=("creation_time", "start_time", "end_time"),
        total_path=None,
    ),
    MULTI_PARTY_CALL_PARTICIPANTS: PlivoEndpointConfig(
        name=MULTI_PARTY_CALL_PARTICIPANTS,
        # Fanned out per MPC. Plivo serves participants by MPC name only while the call is ongoing,
        # so the listing is addressed by UUID, which also works for ended calls.
        path="MultiPartyCall/uuid_{mpc_uuid}/Participant/",
        # member_id is only unique within its MPC.
        primary_keys=["mpc_uuid", "member_id"],
        # The participant listing has no time filter, so incremental syncs filter the parent MPC
        # list by end_time and stamp it onto each participant as mpc_end_time.
        incremental_fields=[incremental_field("mpc_end_time")],
        time_filter_field="end_time",
        datetime_fields=("join_time", "exit_time"),
        total_path=None,
    ),
    USAGE_SUMMARY: PlivoEndpointConfig(
        name=USAGE_SUMMARY,
        path="UsageSummary/",
        primary_keys=["id"],
        incremental_fields=[incremental_field("from_date")],
        time_filter_field="from_date",
        partition_key="from_date",
        datetime_fields=("from_date", "to_date"),
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
    "numbers": "Phone numbers rented on your Plivo account, with their capabilities, rates and linked application.",
    MULTI_PARTY_CALLS: "Multiparty calls (MPCs): conference-style calls with several participants.",
    MULTI_PARTY_CALL_PARTICIPANTS: "Participants of each multiparty call, with their role and join and exit details.",
    USAGE_SUMMARY: (
        "Daily billed usage per product, type, country and direction, plus other charges such as number rentals. "
        "The first sync backfills the last 365 days."
    ),
}
