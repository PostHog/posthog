from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# The pagination guide (api.ownerreservations.com/help/guides/api-pagination-etags) documents a
# default page size of 20 and a maximum of 100; always request the max to minimise round trips
# against the 300-requests-per-5-minutes rate limit.
PAGE_LIMIT = 100

# Sent as a "give me everything" value on endpoints that require a since-style filter but have
# no watermark yet (first sync, or an endpoint we never expose as incremental).
EPOCH = "1970-01-01T00:00:00Z"


def _updated_utc_incremental_field() -> list[IncrementalField]:
    return [
        {
            "label": "updated_utc",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_utc",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@frozen
class OwnerRezEndpointConfig:
    name: str
    path: str  # under /v2
    # Query param OwnerRez accepts for a UTC "since" filter, if any (e.g. "since_utc",
    # "created_since_utc"). None means the endpoint has no time filter at all.
    since_param: Optional[str] = None
    # The endpoint's list action 400s unless since_param (or an alternate identifying filter we
    # don't use, e.g. property_ids) is present on every request — so EPOCH is sent even outside
    # incremental mode. Confirmed per-endpoint against the published OpenAPI spec descriptions.
    since_required: bool = False
    # Non-empty only when since_param maps onto a field OwnerRez actually returns on the row, so
    # the pipeline can compute the next watermark from synced data. Several endpoints document a
    # since_utc filter (query the OpenAPI spec's ViewModel schemas) but return no comparable
    # timestamp column, so incremental sync isn't verifiable for them and they stay full refresh.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: Optional[str] = None


OWNERREZ_ENDPOINTS: dict[str, OwnerRezEndpointConfig] = {
    "Bookings": OwnerRezEndpointConfig(
        name="Bookings",
        path="/v2/bookings",
        since_param="since_utc",
        since_required=True,  # docs: "Either property_ids or since_utc is required."
        incremental_fields=_updated_utc_incremental_field(),
        partition_key="created_utc",
    ),
    "Payments": OwnerRezEndpointConfig(
        name="Payments",
        path="/v2/payments",
        # since_utc exists but PaymentViewModel has no updated_utc-style column to checkpoint
        # against — full refresh only.
        partition_key="collected_utc",
    ),
    "Guests": OwnerRezEndpointConfig(
        name="Guests",
        path="/v2/guests",
        since_param="created_since_utc",
        since_required=True,  # docs: "Either q or created_since_utc is required."
        # GuestModel returns no created/updated timestamp column, so this can never be
        # incremental — every sync sends created_since_utc=EPOCH to fetch the full list.
        partition_key=None,
    ),
    "Properties": OwnerRezEndpointConfig(
        name="Properties",
        path="/v2/properties",
        partition_key=None,
    ),
    "Quotes": OwnerRezEndpointConfig(
        name="Quotes",
        path="/v2/quotes",
        since_param="since_utc",
        incremental_fields=_updated_utc_incremental_field(),
        partition_key="created_utc",
    ),
    "Deposits": OwnerRezEndpointConfig(
        name="Deposits",
        path="/v2/deposits",
        # since_utc exists but DepositViewModel has no updated_utc-style column.
        partition_key="deposited_utc",
    ),
    "Fees": OwnerRezEndpointConfig(
        name="Fees",
        path="/v2/fees",
        # since_utc exists but FeeViewModel returns no date field at all.
        partition_key=None,
    ),
    "Refunds": OwnerRezEndpointConfig(
        name="Refunds",
        path="/v2/refunds",
        # since_utc exists but RefundViewModel has no updated_utc-style column.
        partition_key="paid_utc",
    ),
    "Reviews": OwnerRezEndpointConfig(
        name="Reviews",
        path="/v2/reviews",
        since_param="since_utc",
        incremental_fields=_updated_utc_incremental_field(),
        partition_key="created_utc",
    ),
}

ENDPOINTS = tuple(OWNERREZ_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in OWNERREZ_ENDPOINTS.items()
}
