from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Twilio serves resources from several hosts. The legacy 2010-04-01 Account API lives on the main host;
# newer product APIs (Verify, Messaging Services, Conversations) each sit on their own subdomain.
TWILIO_API_HOST = "https://api.twilio.com"
TWILIO_VERIFY_HOST = "https://verify.twilio.com"

# The ceiling the legacy Account API documents and honors. The Verify API documents the same
# ceiling but does not honor it: its error 60373 ("Invalid page size") puts the real range at 1-25.
# https://www.twilio.com/docs/api/errors/60373
DEFAULT_PAGE_SIZE = 1000


def _datetime_field(name: str, nullable: bool = False) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
        "nullable": nullable,
    }


@dataclass
class TwilioEndpointConfig:
    name: str
    # For account-scoped endpoints, the suffix after `/2010-04-01/Accounts/{account_sid}/`, e.g.
    # "Messages.json". For endpoints on another host, the full root-relative path, e.g. "/v2/Services".
    path: str
    # JSON key wrapping the array of resources in a list response, e.g. "messages".
    response_key: str
    primary_key: str = "sid"
    # Host serving this resource. Defaults to the legacy Account API host.
    base_url: str = TWILIO_API_HOST
    # Whether `path` is prefixed with the `/2010-04-01/Accounts/{account_sid}/` Account resource path.
    # The newer subdomain APIs are not account-scoped, so they carry their full path instead.
    account_scoped: bool = True
    # Stable, never-changing timestamp used for partitioning (Twilio returns these as RFC 2822 strings on
    # the legacy API, ISO 8601 on the newer ones).
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Maps an advertised incremental field to the Twilio query-filter base name (operator appended at request time).
    # e.g. {"date_sent": "DateSent"} produces `DateSent>=<date>`.
    incremental_filter_params: dict[str, str] = field(default_factory=dict)
    # Operator appended to the filter base name. The legacy API takes an inclusive `>=` (encoded via a
    # `DateSent>` param name + `=` separator); the Verify API takes a bare `DateCreatedAfter` param, so
    # it uses no operator.
    filter_operator: str = ">"
    # How to format the incremental watermark for the filter value. The legacy API takes a day-granular
    # date; the Verify API takes an ISO 8601 GMT datetime.
    date_filter_format: Literal["date", "datetime"] = "date"
    # Twilio list endpoints that filter by date return rows newest-first and offer no ascending option.
    sort_mode: SortMode = "asc"
    # Rows per page. `None` sends no `PageSize` at all, leaving Twilio on its default of 50.
    page_size: Optional[int] = DEFAULT_PAGE_SIZE


TWILIO_ENDPOINTS: dict[str, TwilioEndpointConfig] = {
    "messages": TwilioEndpointConfig(
        name="messages",
        path="Messages.json",
        response_key="messages",
        partition_key="date_created",
        incremental_fields=[_datetime_field("date_sent", nullable=True)],
        incremental_filter_params={"date_sent": "DateSent"},
        sort_mode="desc",
    ),
    "calls": TwilioEndpointConfig(
        name="calls",
        path="Calls.json",
        response_key="calls",
        partition_key="date_created",
        incremental_fields=[
            _datetime_field("start_time", nullable=True),
            _datetime_field("end_time", nullable=True),
        ],
        incremental_filter_params={"start_time": "StartTime", "end_time": "EndTime"},
        sort_mode="desc",
    ),
    "recordings": TwilioEndpointConfig(
        name="recordings",
        path="Recordings.json",
        response_key="recordings",
        partition_key="date_created",
        incremental_fields=[_datetime_field("date_created")],
        incremental_filter_params={"date_created": "DateCreated"},
        sort_mode="desc",
    ),
    "conferences": TwilioEndpointConfig(
        name="conferences",
        path="Conferences.json",
        response_key="conferences",
        partition_key="date_created",
        incremental_fields=[
            _datetime_field("date_created"),
            _datetime_field("date_updated", nullable=True),
        ],
        incremental_filter_params={"date_created": "DateCreated", "date_updated": "DateUpdated"},
        sort_mode="desc",
    ),
    "addresses": TwilioEndpointConfig(
        name="addresses",
        path="Addresses.json",
        response_key="addresses",
    ),
    "applications": TwilioEndpointConfig(
        name="applications",
        path="Applications.json",
        response_key="applications",
        partition_key="date_created",
    ),
    "incoming_phone_numbers": TwilioEndpointConfig(
        name="incoming_phone_numbers",
        path="IncomingPhoneNumbers.json",
        response_key="incoming_phone_numbers",
        partition_key="date_created",
    ),
    "keys": TwilioEndpointConfig(
        name="keys",
        path="Keys.json",
        response_key="keys",
        partition_key="date_created",
    ),
    "outgoing_caller_ids": TwilioEndpointConfig(
        name="outgoing_caller_ids",
        path="OutgoingCallerIds.json",
        response_key="outgoing_caller_ids",
        partition_key="date_created",
    ),
    "queues": TwilioEndpointConfig(
        name="queues",
        path="Queues.json",
        response_key="queues",
        partition_key="date_created",
    ),
    "transcriptions": TwilioEndpointConfig(
        name="transcriptions",
        path="Transcriptions.json",
        response_key="transcriptions",
        partition_key="date_created",
    ),
    # Aggregated usage per category on the account. Records have no `sid`; each category appears once.
    "usage_records": TwilioEndpointConfig(
        name="usage_records",
        path="Usage/Records.json",
        response_key="usage_records",
        primary_key="category",
    ),
    # Verify API (verify.twilio.com/v2), not account-scoped and paginated via `meta.next_page_url`.
    # Neither Verify endpoint sends a page size: Twilio answers `PageSize=1000` with a 400 here, and
    # the range it actually accepts is contested between its own reference (1-1000) and its error
    # dictionary (1-25). A page size we never send can't be rejected, so both take the server
    # default instead of us picking a number off whichever doc is wrong.
    "verification_services": TwilioEndpointConfig(
        name="verification_services",
        path="/v2/Services",
        response_key="services",
        base_url=TWILIO_VERIFY_HOST,
        account_scoped=False,
        partition_key="date_created",
        page_size=None,
    ),
    # Verification attempts are retained by Twilio for only 30 days, so this is synced incrementally on
    # `DateCreatedAfter` to keep pulling the freshest data every run.
    "verification_attempts": TwilioEndpointConfig(
        name="verification_attempts",
        path="/v2/Attempts",
        response_key="attempts",
        base_url=TWILIO_VERIFY_HOST,
        account_scoped=False,
        partition_key="date_created",
        incremental_fields=[_datetime_field("date_created")],
        incremental_filter_params={"date_created": "DateCreatedAfter"},
        filter_operator="",
        date_filter_format="datetime",
        sort_mode="desc",
        page_size=None,
    ),
}

ENDPOINTS = tuple(TWILIO_ENDPOINTS.keys())

# Twilio grants the Keys resource (/Accounts/{SID}/Keys) only to the Auth Token and to Main API keys.
# Standard and Restricted API keys get a 401 with error 20003 on it, so the table has to be reported
# as unreachable for those credentials instead of read as a failed credential check.
# https://www.twilio.com/docs/iam/api-keys
MAIN_KEY_ONLY_ENDPOINTS = frozenset({"keys"})

# `get_endpoint_permissions` only runs on the schema-picker path, so one-shot setup would otherwise
# enable a table it has no way to check. Defaulting these off covers both paths, since the picker and
# `build_default_schemas` honor it, and the recommended credential is a Standard key.
SHOULD_SYNC_DEFAULT: dict[str, bool] = {name: name not in MAIN_KEY_ONLY_ENDPOINTS for name in ENDPOINTS}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TWILIO_ENDPOINTS.items()
}
