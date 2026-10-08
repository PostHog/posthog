from datetime import date
from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

API_BASE_URL = "https://api.xsolla.com/merchant"
API_DOCS_URL = "https://developers.xsolla.com/api/getting-started/"
PAGE_SIZE = 100
# Xsolla has no endpoint that reports when a merchant's history starts, so date-bounded endpoints
# walk forward from a fixed date that predates Pay Station.
HISTORY_START = date(2010, 1, 1)
# Incremental transaction syncs read this many days again. This catches status changes on recent
# transactions, and rows that arrived out of order inside the last window.
TRANSACTIONS_LOOKBACK_DAYS = 7

AUTH_ERROR = "Xsolla rejected the credentials. Check the merchant ID and the company API key."
RESPONSE_ACTIONS: list[ResponseAction] = [
    {"status_code": 401, "action": "raise", "message": AUTH_ERROR},
    {"status_code": 403, "action": "raise", "message": AUTH_ERROR},
]


@frozen
class XsollaEndpoint:
    path: str
    primary_keys: tuple[str, ...] = ("id",)
    # Project endpoints are read once per project that the merchant owns.
    scope: Literal["merchant", "project"] = "merchant"
    paginated: bool = True
    # Endpoints that need datetime_from/datetime_to are read in windows of this many days.
    window_days: int | None = None
    # Nested values copied to the row root, so that they can be primary keys or incremental fields.
    lifted_fields: tuple[tuple[str, str, str], ...] = ()
    partition_key: str | None = None


ENDPOINTS: dict[str, XsollaEndpoint] = {
    "transactions": XsollaEndpoint(
        path="merchants/{merchant_id}/reports/transactions/search.json",
        window_days=7,
        lifted_fields=(("id", "transaction", "id"), ("create_date", "transaction", "create_date")),
        partition_key="create_date",
    ),
    "subscriptions": XsollaEndpoint(
        path="merchants/{merchant_id}/subscriptions",
        partition_key="date_create",
    ),
    "subscription_payments": XsollaEndpoint(
        path="projects/{project_id}/subscriptions/payments",
        primary_keys=("project_id", "id"),
        scope="project",
        partition_key="date_payment",
    ),
    "subscription_plans": XsollaEndpoint(
        path="projects/{project_id}/subscriptions/plans",
        primary_keys=("project_id", "id"),
        scope="project",
    ),
    "subscription_products": XsollaEndpoint(
        path="projects/{project_id}/subscriptions/products",
        primary_keys=("project_id", "id"),
        scope="project",
    ),
    "payouts": XsollaEndpoint(
        path="merchants/{merchant_id}/reports/transfers",
        paginated=False,
        # Xsolla rejects report periods longer than 92 days.
        window_days=92,
        lifted_fields=(("id", "payout", "id"),),
    ),
    "reports": XsollaEndpoint(
        path="merchants/{merchant_id}/reports",
        primary_keys=("report_id",),
        paginated=False,
        window_days=92,
    ),
    "promotions": XsollaEndpoint(
        path="merchants/{merchant_id}/promotions",
        paginated=False,
    ),
    "projects": XsollaEndpoint(
        path="merchants/{merchant_id}/projects",
        paginated=False,
    ),
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "transactions": [
        {
            "label": "create_date",
            "type": IncrementalFieldType.DateTime,
            "field": "create_date",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}
