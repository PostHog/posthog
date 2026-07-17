from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _datetime_incremental_fields(field_name: str) -> list[IncrementalField]:
    # Smartwaiver's only server-side time filter is `fromDts`/`toDts`, which keys off the
    # resource's creation timestamp. Advertising just that field keeps the user's chosen cursor
    # aligned with what the API filters on.
    return [
        {
            "label": field_name,
            "type": IncrementalFieldType.DateTime,
            "field": field_name,
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@dataclass
class SmartwaiverEndpointConfig:
    name: str
    path: str  # Path under https://api.smartwaiver.com, e.g. "/v4/waivers"
    # Key of the record list in the JSON response envelope (`type` matches it).
    response_key: str
    # Whether the endpoint exposes the server-side `fromDts` timestamp filter.
    supports_incremental: bool = False
    # Field `fromDts` filters on; also used as the incremental cursor.
    incremental_field: Optional[str] = None
    # Stable creation-time field to partition by. None when the table is small enough not to bother.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


SMARTWAIVER_ENDPOINTS: dict[str, SmartwaiverEndpointConfig] = {
    # Waiver templates. No pagination — the endpoint returns every template in one response, and
    # accounts hold at most a handful, so it's full refresh only.
    "templates": SmartwaiverEndpointConfig(
        name="templates",
        path="/v4/templates",
        response_key="templates",
        primary_keys=["templateId"],
    ),
    # Signed waiver summaries. `fromDts` filters server-side on the signing timestamp (`createdOn`),
    # so incremental syncs only pull waivers signed after the watermark.
    "waivers": SmartwaiverEndpointConfig(
        name="waivers",
        path="/v4/waivers",
        response_key="waivers",
        supports_incremental=True,
        incremental_field="createdOn",
        partition_key="createdOn",
        incremental_fields=_datetime_incremental_fields("createdOn"),
        primary_keys=["waiverId"],
    ),
    # Participant check-ins. `fromDts`/`toDts` are required and filter server-side on the check-in
    # timestamp (`date`). One waiver can have several check-in records (one per signer, and -1 for
    # the guardian), so the key includes `position`.
    "checkins": SmartwaiverEndpointConfig(
        name="checkins",
        path="/v4/checkins",
        response_key="checkins",
        supports_incremental=True,
        incremental_field="date",
        partition_key="date",
        incremental_fields=_datetime_incremental_fields("date"),
        primary_keys=["checkinId", "position"],
    ),
}

ENDPOINTS = tuple(SMARTWAIVER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SMARTWAIVER_ENDPOINTS.items()
}
