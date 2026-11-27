import dataclasses

from products.warehouse_sources.sources.sdk import IncrementalField, incremental_field


@dataclasses.dataclass(frozen=True)
class TelnyxEndpoint:
    """Declarative metadata for one Telnyx table.

    Detail Record Search tables share one physical endpoint (`GET /v2/detail_records`) and are
    distinguished only by `filter[record_type]`. Lookup tables (phone numbers, profiles, ...) each
    have their own list path and set `record_type` to None.
    """

    name: str
    table_name: str
    record_type: str | None
    primary_key: list[str]
    # A stable timestamp field used for datetime partitioning (and, when set, as the
    # `filter[<field>][gte]` incremental cursor). Never `updated_at`-like fields.
    partition_key: str
    # Set only when the record's own response schema documents this field AND Telnyx's docs
    # demonstrate a `filter[<field>][gte]`/`[lt]` server-side filter for it. Record types
    # without a documented `created_at`-equivalent stay full refresh rather than guessing that
    # the generic attribute filter also windows time reliably for them.
    incremental_field: str | None = None
    # `sort` sent on full refresh. None sends no `sort`, for list endpoints that document none.
    full_refresh_sort: str | None = None
    path: str = "/v2/detail_records"
    # Detail Record Search caps `page[size]` at 50; the general list endpoints allow up to 250.
    page_size: int = 50
    # Fields dropped from every row before it is written, e.g. credentials the API returns.
    excluded_fields: tuple[str, ...] = ()


TELNYX_ENDPOINTS: dict[str, TelnyxEndpoint] = {
    "MessagingDetailRecords": TelnyxEndpoint(
        name="MessagingDetailRecords",
        table_name="messaging_detail_records",
        record_type="messaging",
        # SMS/MMS records carry `uuid`, but RCS records (`agent_name`/`product_name` present
        # instead) carry no `uuid` field at all, only `id`. The writer already merges on
        # whichever configured key survives into a given batch, so listing both lets each
        # record shape merge on its own identifier instead of failing incremental syncs on tables
        # that mix RCS in with SMS/MMS.
        primary_key=["uuid", "id"],
        partition_key="created_at",
        full_refresh_sort="created_at",
        incremental_field="created_at",
    ),
    "VerifyDetailRecords": TelnyxEndpoint(
        name="VerifyDetailRecords",
        table_name="verify_detail_records",
        record_type="verify",
        primary_key=["id"],
        partition_key="created_at",
        full_refresh_sort="created_at",
        incremental_field="created_at",
    ),
    "WirelessUsageDetailRecords": TelnyxEndpoint(
        name="WirelessUsageDetailRecords",
        table_name="wireless_usage_detail_records",
        record_type="wireless",
        primary_key=["id"],
        partition_key="created_at",
        full_refresh_sort="created_at",
        incremental_field="created_at",
    ),
    "MediaStorageDetailRecords": TelnyxEndpoint(
        name="MediaStorageDetailRecords",
        table_name="media_storage_detail_records",
        record_type="media_storage",
        primary_key=["id"],
        partition_key="created_at",
        full_refresh_sort="created_at",
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
        full_refresh_sort="started_at",
    ),
    "ConferenceParticipantDetailRecords": TelnyxEndpoint(
        name="ConferenceParticipantDetailRecords",
        table_name="conference_participant_detail_records",
        record_type="conference-participant",
        primary_key=["id"],
        partition_key="joined_at",
        full_refresh_sort="joined_at",
    ),
    "AmdDetailRecords": TelnyxEndpoint(
        name="AmdDetailRecords",
        table_name="amd_detail_records",
        record_type="amd",
        primary_key=["id"],
        partition_key="invoked_at",
        full_refresh_sort="invoked_at",
    ),
    # Lookup tables that resolve the IDs carried by the detail records. None of these list
    # endpoints has a server-side time filter, so they ship full refresh.
    "PhoneNumbers": TelnyxEndpoint(
        name="PhoneNumbers",
        table_name="phone_numbers",
        record_type=None,
        primary_key=["id"],
        partition_key="created_at",
        # `created_at` is not an allowed sort value here; the implicit default is `created_at`
        # descending, which shifts page boundaries as numbers are bought mid-sync.
        full_refresh_sort="phone_number",
        path="/v2/phone_numbers",
        page_size=250,
        # The port-out protection PIN.
        excluded_fields=("external_pin",),
    ),
    "MessagingProfiles": TelnyxEndpoint(
        name="MessagingProfiles",
        table_name="messaging_profiles",
        record_type=None,
        primary_key=["id"],
        partition_key="created_at",
        path="/v2/messaging_profiles",
        page_size=250,
        excluded_fields=("v1_secret",),
    ),
    # `/connections` lists every connection type with the shared fields. The typed
    # `/credential_connections` and `/ip_connections` lists are a subset of it, and the
    # credential one returns SIP passwords.
    "Connections": TelnyxEndpoint(
        name="Connections",
        table_name="connections",
        record_type=None,
        primary_key=["id"],
        partition_key="created_at",
        full_refresh_sort="created_at",
        path="/v2/connections",
        page_size=250,
    ),
    "Conferences": TelnyxEndpoint(
        name="Conferences",
        table_name="conferences",
        record_type=None,
        primary_key=["id"],
        partition_key="created_at",
        path="/v2/conferences",
        page_size=250,
    ),
}

ENDPOINTS: tuple[str, ...] = tuple(TELNYX_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    endpoint.name: [incremental_field(endpoint.incremental_field)]
    for endpoint in TELNYX_ENDPOINTS.values()
    if endpoint.incremental_field
}
