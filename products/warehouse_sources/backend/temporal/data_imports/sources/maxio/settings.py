"""Maxio (Advanced Billing / Chargify) source settings and endpoint catalog."""

import dataclasses

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Maxio Advanced Billing sites are hosted per-region on different domains. The
# subdomain is the site's "site name"; the region is chosen when the account is
# provisioned (see maxio-com/ab-python-sdk `Environment`).
MAXIO_BASE_URLS: dict[str, str] = {
    "us": "https://{subdomain}.chargify.com",
    "eu": "https://{subdomain}.ebilling.maxio.com",
}

# Maximum allowed by the API; any larger value is clamped server-side to 200.
PAGE_SIZE = 200

# `start_datetime` filters are interpreted in the site's configured timezone (not UTC)
# unless a timezone is embedded in the value. We format watermarks as naive UTC and
# re-read a trailing day each incremental run to cover the maximum UTC<->site-timezone
# skew; the merge on primary keys dedupes the overlap.
TIMEZONE_SKEW_LOOKBACK_SECONDS = 24 * 60 * 60


@dataclasses.dataclass(frozen=True)
class MaxioEndpointConfig:
    path: str
    # JSONPath into the response body. Most list endpoints return a bare array of
    # `{"<resource>": {...}}` wrappers; invoices/credit notes wrap the array in a key.
    data_selector: str
    primary_keys: list[str]
    # Stable datetime field used for delta partitioning; None disables partitioning.
    partition_keys: list[str] | None
    incremental_fields: list[IncrementalField]
    # Value for the `date_field` query param when syncing incrementally. Only endpoints
    # whose rows can also be *ordered* by a matching stable field advertise incremental
    # sync — the pipeline checkpoints an ascending watermark per batch.
    incremental_date_field: str | None = None
    # Events-style monotonic integer cursor (`since_id`, inclusive) instead of a
    # datetime window.
    uses_since_id: bool = False
    # Static params sent on every request.
    extra_params: dict[str, str | int | bool] = dataclasses.field(default_factory=dict)
    # Explicit stable sort applied on every run (guards against page-boundary drift).
    sort_params: dict[str, str] = dataclasses.field(default_factory=dict)
    # Sort override when syncing incrementally, matching the incremental cursor so
    # rows arrive in ascending cursor order.
    incremental_sort_params: dict[str, str] = dataclasses.field(default_factory=dict)


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


ENDPOINTS: dict[str, MaxioEndpointConfig] = {
    "customers": MaxioEndpointConfig(
        path="/customers.json",
        data_selector="[*].customer",
        primary_keys=["id"],
        partition_keys=["created_at"],
        # `direction` sorts customers by time of creation only, so `created_at` is the
        # only cursor whose arrival order matches the watermark. `updated_at` filtering
        # exists server-side but rows can't be ordered by it, which would corrupt the
        # per-batch ascending watermark checkpoint.
        incremental_fields=[_datetime_field("created_at")],
        incremental_date_field="created_at",
        sort_params={"direction": "asc"},
    ),
    "subscriptions": MaxioEndpointConfig(
        path="/subscriptions.json",
        data_selector="[*].subscription",
        primary_keys=["id"],
        partition_keys=["created_at"],
        incremental_fields=[_datetime_field("updated_at")],
        incremental_date_field="updated_at",
        sort_params={"sort": "created_at", "direction": "asc"},
        incremental_sort_params={"sort": "updated_at", "direction": "asc"},
    ),
    "invoices": MaxioEndpointConfig(
        path="/invoices.json",
        data_selector="invoices",
        primary_keys=["uid"],
        partition_keys=["created_at"],
        incremental_fields=[_datetime_field("updated_at")],
        incremental_date_field="updated_at",
        extra_params={
            "line_items": "true",
            "discounts": "true",
            "taxes": "true",
            "credits": "true",
            "payments": "true",
            "refunds": "true",
        },
        sort_params={"sort": "created_at", "direction": "asc"},
        incremental_sort_params={"sort": "updated_at", "direction": "asc"},
    ),
    "products": MaxioEndpointConfig(
        path="/products.json",
        data_selector="[*].product",
        primary_keys=["id"],
        partition_keys=["created_at"],
        # Server-side date filtering exists, but the endpoint exposes no sort params so
        # arrival order is undefined — full refresh only (the table is small anyway).
        incremental_fields=[],
        extra_params={"include_archived": "true"},
    ),
    "product_families": MaxioEndpointConfig(
        path="/product_families.json",
        data_selector="[*].product_family",
        primary_keys=["id"],
        partition_keys=["created_at"],
        incremental_fields=[],
    ),
    "coupons": MaxioEndpointConfig(
        path="/coupons.json",
        data_selector="[*].coupon",
        primary_keys=["id"],
        partition_keys=["created_at"],
        # Date filtering is only available via nested `filter[...]` params whose
        # serialization we can't verify against a live site — full refresh only.
        incremental_fields=[],
    ),
    "components": MaxioEndpointConfig(
        path="/components.json",
        data_selector="[*].component",
        primary_keys=["id"],
        partition_keys=["created_at"],
        incremental_fields=[],
        extra_params={"include_archived": "true"},
    ),
    "payment_profiles": MaxioEndpointConfig(
        path="/payment_profiles.json",
        data_selector="[*].payment_profile",
        primary_keys=["id"],
        # Payment profiles carry no creation timestamp.
        partition_keys=None,
        incremental_fields=[],
    ),
    "events": MaxioEndpointConfig(
        path="/events.json",
        data_selector="[*].event",
        primary_keys=["id"],
        partition_keys=["created_at"],
        incremental_fields=[
            {
                "label": "id",
                "type": IncrementalFieldType.Integer,
                "field": "id",
                "field_type": IncrementalFieldType.Integer,
            }
        ],
        uses_since_id=True,
        sort_params={"direction": "asc"},
    ),
    "credit_notes": MaxioEndpointConfig(
        path="/credit_notes.json",
        data_selector="credit_notes",
        primary_keys=["uid"],
        # Credit notes expose no stable creation timestamp (`issue_date` can be absent
        # on drafts), so partitioning stays off.
        partition_keys=None,
        incremental_fields=[],
        extra_params={
            "line_items": "true",
            "discounts": "true",
            "taxes": "true",
            "applications": "true",
            "refunds": "true",
        },
    ),
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ENDPOINTS.items()
}
