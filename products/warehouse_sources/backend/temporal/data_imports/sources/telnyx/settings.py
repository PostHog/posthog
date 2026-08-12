import dataclasses

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField


@dataclasses.dataclass(frozen=True)
class TelnyxEndpoint:
    """Declarative metadata for one Telnyx Detail Record Search `record_type`.

    Every record type shares the same physical endpoint (`GET /v2/detail_records`) and is
    distinguished only by `filter[record_type]`, so each entry here maps to a distinct table.
    """

    name: str
    table_name: str
    record_type: str
    primary_key: list[str]
    # A stable timestamp field used for datetime partitioning (and, when set, as the
    # `filter[<field>][gte]` incremental cursor). Never `updated_at`-like fields.
    partition_key: str
    # Set only when the record's own response schema documents this field AND Telnyx's docs
    # demonstrate a `filter[<field>][gte]`/`[lt]` server-side filter for it. Record types
    # without a documented `created_at`-equivalent stay full refresh rather than guessing that
    # the generic attribute filter also windows time reliably for them.
    incremental_field: str | None = None


TELNYX_ENDPOINTS: dict[str, TelnyxEndpoint] = {
    "MessagingDetailRecords": TelnyxEndpoint(
        name="MessagingDetailRecords",
        table_name="messaging_detail_records",
        record_type="messaging",
        primary_key=["uuid"],
        partition_key="created_at",
        incremental_field="created_at",
    ),
    "VerifyDetailRecords": TelnyxEndpoint(
        name="VerifyDetailRecords",
        table_name="verify_detail_records",
        record_type="verify",
        primary_key=["id"],
        partition_key="created_at",
        incremental_field="created_at",
    ),
    "WirelessUsageDetailRecords": TelnyxEndpoint(
        name="WirelessUsageDetailRecords",
        table_name="wireless_usage_detail_records",
        record_type="wireless",
        primary_key=["id"],
        partition_key="created_at",
        incremental_field="created_at",
    ),
    "MediaStorageDetailRecords": TelnyxEndpoint(
        name="MediaStorageDetailRecords",
        table_name="media_storage_detail_records",
        record_type="media_storage",
        primary_key=["id"],
        partition_key="created_at",
        incremental_field="created_at",
    ),
    # Conference/participant/AMD records have no documented `created_at`-equivalent filter, only
    # their own start/join/invocation timestamp — Telnyx's docs only demonstrate the
    # `filter[created_at]` example against messaging records, so these ship full refresh.
    "ConferenceDetailRecords": TelnyxEndpoint(
        name="ConferenceDetailRecords",
        table_name="conference_detail_records",
        record_type="conference",
        primary_key=["id"],
        partition_key="started_at",
    ),
    "ConferenceParticipantDetailRecords": TelnyxEndpoint(
        name="ConferenceParticipantDetailRecords",
        table_name="conference_participant_detail_records",
        record_type="conference-participant",
        primary_key=["id"],
        partition_key="joined_at",
    ),
    "AmdDetailRecords": TelnyxEndpoint(
        name="AmdDetailRecords",
        table_name="amd_detail_records",
        record_type="amd",
        primary_key=["id"],
        partition_key="invoked_at",
    ),
}

ENDPOINTS: tuple[str, ...] = tuple(TELNYX_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    endpoint.name: [incremental_field(endpoint.incremental_field)]
    for endpoint in TELNYX_ENDPOINTS.values()
    if endpoint.incremental_field
}
