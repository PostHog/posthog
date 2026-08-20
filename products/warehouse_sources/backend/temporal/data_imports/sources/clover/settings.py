from dataclasses import dataclass, field
from typing import Any

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Clover runs the same v3 API on one host per deployment region, and a merchant only exists on
# the host of the region they were onboarded in — pointing at the wrong one returns a 404.
CLOVER_REGION_HOSTS: dict[str, str] = {
    "na": "https://api.clover.com",
    "eu": "https://api.eu.clover.com",
    "latam": "https://api.la.clover.com",
    "sandbox": "https://apisandbox.dev.clover.com",
}
DEFAULT_REGION = "na"

# A Clover app is registered per region and can only authorize merchants in that region, so each
# region connects through its own PostHog OAuth app (see CLOVER_OAUTH_REGIONS in
# posthog/models/integration/oauth.py). This maps the form's region to the integration kind that serves it.
CLOVER_REGION_INTEGRATION_KINDS: dict[str, str] = {
    "na": "clover",
    "eu": "clover-eu",
    "latam": "clover-latam",
    "sandbox": "clover-sandbox",
}
CLOVER_INTEGRATION_KIND_REGIONS: dict[str, str] = {
    kind: region for region, kind in CLOVER_REGION_INTEGRATION_KINDS.items()
}

# `limit` defaults to 100 and is capped at 1000.
PAGE_SIZE = 1000

# Clover rejects any time-filtered query spanning more than 90 days, so a filtered walk is split
# into windows. 89 days keeps every request inside the cap with room for the inclusive bounds.
FILTER_WINDOW_MS = 89 * 24 * 60 * 60 * 1000

# Clover's filter grammar offers only >=, <=, = and != — there is no strict <, so a window's upper
# bound is inclusive and the next window starts one millisecond past it.
FILTERABLE_TIME_FIELDS = ("modifiedTime", "createdTime", "clientCreatedTime")


def _time_field(name: str) -> IncrementalField:
    """Advertise a Clover timestamp as a cursor.

    Clover returns timestamps as epoch milliseconds, so the stored column (and therefore the
    watermark we build the ``filter`` from) is an integer even though users pick it as a datetime.
    """
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.Integer,
    }


@dataclass
class CloverEndpointConfig:
    name: str
    # Collection path under /v3/merchants/{merchant_id}/.
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Static query params sent on every request (e.g. `expand`).
    params: dict[str, Any] = field(default_factory=dict)
    # Only fields in FILTERABLE_TIME_FIELDS can be pushed down as a server-side `filter`; an
    # endpoint that exposes none of them is full refresh only (see "Incremental sync guidance" —
    # a client-side cursor would still walk every page, so it isn't incremental).
    incremental_fields: list[IncrementalField] = field(default_factory=list)

    @property
    def supports_incremental(self) -> bool:
        return bool(self.incremental_fields)

    @property
    def filterable_fields(self) -> tuple[str, ...]:
        return tuple(f["field"] for f in self.incremental_fields)


CLOVER_ENDPOINTS: dict[str, CloverEndpointConfig] = {
    "orders": CloverEndpointConfig(
        name="orders",
        path="orders",
        # Line items are the grain most order analysis needs and have no top-level collection of
        # their own. Clover caps an expanded nested collection at 100 elements, which no realistic
        # order exceeds.
        params={"expand": "lineItems"},
        incremental_fields=[_time_field("modifiedTime"), _time_field("createdTime")],
    ),
    "payments": CloverEndpointConfig(
        name="payments",
        path="payments",
        incremental_fields=[_time_field("modifiedTime"), _time_field("createdTime")],
    ),
    "refunds": CloverEndpointConfig(
        name="refunds",
        path="refunds",
        incremental_fields=[_time_field("createdTime")],
    ),
    "credits": CloverEndpointConfig(
        name="credits",
        path="credits",
        incremental_fields=[_time_field("createdTime")],
    ),
    "items": CloverEndpointConfig(
        name="items",
        path="items",
        incremental_fields=[_time_field("modifiedTime")],
    ),
    # The remaining endpoints are small configuration/dimension tables whose objects carry no
    # timestamp Clover will filter on, so they full refresh each sync.
    "categories": CloverEndpointConfig(name="categories", path="categories"),
    "modifier_groups": CloverEndpointConfig(name="modifier_groups", path="modifier_groups"),
    "customers": CloverEndpointConfig(name="customers", path="customers"),
    "employees": CloverEndpointConfig(name="employees", path="employees"),
    "shifts": CloverEndpointConfig(name="shifts", path="shifts"),
    "tenders": CloverEndpointConfig(name="tenders", path="tenders"),
    "discounts": CloverEndpointConfig(name="discounts", path="discounts"),
    "tax_rates": CloverEndpointConfig(name="tax_rates", path="tax_rates"),
}

ENDPOINTS = tuple(CLOVER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CLOVER_ENDPOINTS.items()
}
