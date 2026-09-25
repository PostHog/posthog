from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class EasypostEndpointConfig:
    name: str
    # Path segment under https://api.easypost.com/v2/. EasyPost list responses wrap the array
    # under a key matching the resource (e.g. `/shipments` -> {"shipments": [...]}), so the
    # endpoint name doubles as the response collection key.
    path: str
    incremental_fields: list[IncrementalField]
    # Stable creation timestamp used both as the incremental cursor and partition key. EasyPost
    # orders list results newest-first by creation time, so `created_at` is the only field whose
    # ordering the descending pagination + watermark logic can rely on.
    partition_key: Optional[str] = "created_at"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Events are immutable once emitted, so they're append-only. Mutable resources (shipments,
    # trackers, …) still expose `created_at` incremental sync, which appends newly created rows;
    # later mutations to an existing row are only picked up by a full refresh.
    append_only: bool = False
    should_sync_default: bool = True
    # Cursor pagination (before_id + has_more). The lookup endpoints answer with the whole
    # collection in one response and carry no cursor.
    paginated: bool = True
    # Server-side `created_at` filter. Absent from /end_shippers and the lookup endpoints.
    supports_start_datetime: bool = True
    # /carrier_accounts answers with a bare JSON array instead of the usual {"<name>": [...]}.
    returns_bare_list: bool = False
    # Top-level keys dropped from every row before it reaches the warehouse.
    redacted_fields: tuple[str, ...] = ()


def _created_at_fields() -> list[IncrementalField]:
    return [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


# Cursor-paginated list endpoints (before_id/after_id + has_more) that all share the EasyPost
# object shape: a globally-unique prefixed `id`, plus `created_at` / `updated_at` ISO-8601
# timestamps. `start_datetime` filters server-side on `created_at`. `/carrier_accounts` and
# `/metadata/carriers` are lookups answered in a single unpaginated response. `/parcels` has no
# list endpoint and `/webhooks` is unpaginated, so neither is exposed as a sync table here.
EASYPOST_ENDPOINTS: dict[str, EasypostEndpointConfig] = {
    "addresses": EasypostEndpointConfig(
        name="addresses",
        path="/addresses",
        incremental_fields=_created_at_fields(),
    ),
    "batches": EasypostEndpointConfig(
        name="batches",
        path="/batches",
        incremental_fields=_created_at_fields(),
    ),
    "carrier_accounts": EasypostEndpointConfig(
        name="carrier_accounts",
        path="/carrier_accounts",
        # No cursor and no time filter, so full refresh only. EasyPost serves this endpoint to
        # production API keys only, so a source connected with a test key cannot sync it — leave
        # it unselected rather than failing a table the user never asked for.
        incremental_fields=[],
        partition_key=None,
        should_sync_default=False,
        paginated=False,
        supports_start_datetime=False,
        returns_bare_list=True,
        # Carrier credentials. EasyPost masks password-type values but returns the rest in
        # plaintext, and anyone who can query the warehouse can read the synced row.
        redacted_fields=("fields", "credentials", "test_credentials"),
    ),
    "carriers": EasypostEndpointConfig(
        name="carriers",
        path="/metadata/carriers",
        # Platform-wide carrier metadata (service levels, predefined packages, supported
        # options), keyed by the single-word carrier name. It carries no id and no timestamps,
        # so full refresh only.
        incremental_fields=[],
        partition_key=None,
        primary_keys=["name"],
        paginated=False,
        supports_start_datetime=False,
    ),
    "claims": EasypostEndpointConfig(
        name="claims",
        path="/claims",
        incremental_fields=_created_at_fields(),
    ),
    "end_shippers": EasypostEndpointConfig(
        name="end_shippers",
        path="/end_shippers",
        # /end_shippers paginates by cursor but takes no start_datetime, so the descending
        # client-side watermark stop is what bounds an incremental run. EasyPost opens this API
        # to enabled accounts only, so it stays unselected by default.
        incremental_fields=_created_at_fields(),
        should_sync_default=False,
        supports_start_datetime=False,
    ),
    "events": EasypostEndpointConfig(
        name="events",
        path="/events",
        incremental_fields=_created_at_fields(),
        append_only=True,
    ),
    "insurances": EasypostEndpointConfig(
        name="insurances",
        path="/insurances",
        incremental_fields=_created_at_fields(),
    ),
    "pickups": EasypostEndpointConfig(
        name="pickups",
        path="/pickups",
        incremental_fields=_created_at_fields(),
    ),
    "refunds": EasypostEndpointConfig(
        name="refunds",
        path="/refunds",
        incremental_fields=_created_at_fields(),
    ),
    "scan_forms": EasypostEndpointConfig(
        name="scan_forms",
        path="/scan_forms",
        incremental_fields=_created_at_fields(),
    ),
    "shipments": EasypostEndpointConfig(
        name="shipments",
        path="/shipments",
        incremental_fields=_created_at_fields(),
    ),
    "trackers": EasypostEndpointConfig(
        name="trackers",
        path="/trackers",
        incremental_fields=_created_at_fields(),
    ),
}

ENDPOINTS = tuple(EASYPOST_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in EASYPOST_ENDPOINTS.items()
}
