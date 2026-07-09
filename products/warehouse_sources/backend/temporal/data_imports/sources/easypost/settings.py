from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
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
# timestamps. `start_datetime` filters server-side on `created_at`. `/parcels` has no list
# endpoint and `/webhooks` is unpaginated, so neither is exposed as a sync table here.
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
