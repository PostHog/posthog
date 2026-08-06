from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


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
    # Resource path appended after `/2010-04-01/Accounts/{account_sid}/`, e.g. "Messages.json".
    path: str
    # JSON key wrapping the array of resources in a list response, e.g. "messages".
    response_key: str
    primary_key: str = "sid"
    # Stable, never-changing timestamp used for partitioning (Twilio returns these as RFC 2822 strings).
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Maps an advertised incremental field to the Twilio query-filter base name (operator appended at request time).
    # e.g. {"date_sent": "DateSent"} produces `DateSent>=<date>`.
    incremental_filter_params: dict[str, str] = field(default_factory=dict)
    # Twilio list endpoints that filter by date return rows newest-first and offer no ascending option.
    sort_mode: SortMode = "asc"


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
