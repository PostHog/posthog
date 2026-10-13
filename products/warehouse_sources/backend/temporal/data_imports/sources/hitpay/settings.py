from dataclasses import field
from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

PaginationKind = Literal["cursor", "page", "single"]


def _created_at_incremental_fields() -> list[IncrementalField]:
    return [
        {
            "label": "created_at",
            "type": IncrementalFieldType.DateTime,
            "field": "created_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@frozen
class HitpayEndpointConfig:
    name: str
    table_name: str
    path: str
    pagination: PaginationKind = "page"
    # Query param carrying the page number. HitPay is not consistent across endpoints:
    # /v1/payment-requests uses `current_page`, everything else uses `page`.
    page_param: str = "page"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: str | None = "created_at"
    incremental_fields: list[IncrementalField] = field(default_factory=list)


HITPAY_ENDPOINTS: dict[str, HitpayEndpointConfig] = {
    "PaymentRequests": HitpayEndpointConfig(
        name="PaymentRequests",
        table_name="payment_requests",
        path="/v1/payment-requests",
        pagination="page",
        page_param="current_page",
        # No documented date/status-since filter for this endpoint, so it's full refresh only.
    ),
    "Charges": HitpayEndpointConfig(
        name="Charges",
        table_name="charges",
        path="/v1/charges",
        pagination="cursor",
        incremental_fields=_created_at_incremental_fields(),
    ),
    "SubscriptionPlans": HitpayEndpointConfig(
        name="SubscriptionPlans",
        table_name="subscription_plans",
        path="/v1/subscription-plan",
        pagination="page",
        page_param="page",
    ),
    "Customers": HitpayEndpointConfig(
        name="Customers",
        table_name="customers",
        path="/v1/customers",
        pagination="page",
        page_param="page",
    ),
    "RecurringBilling": HitpayEndpointConfig(
        name="RecurringBilling",
        table_name="recurring_billing",
        path="/v1/recurring-billing",
        # HitPay's OpenAPI spec documents no pagination params at all for this endpoint (unlike
        # every sibling list endpoint), so it's fetched as a single page per status filter below.
        pagination="single",
    ),
}

ENDPOINTS = tuple(HITPAY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in HITPAY_ENDPOINTS.items()
}

# GET /v1/recurring-billing filters on `status` and defaults to "active" when the param is
# omitted, so a single unfiltered request would silently hide every canceled/inactive/scheduled/
# retrying subscription. The values are mutually exclusive, so requesting each one in turn covers
# the full table with no duplicate rows across requests.
RECURRING_BILLING_STATUSES = ("active", "scheduled", "retrying", "inactive", "canceled")
