from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField

API_ROOT = "https://api.triplewhale.com/api"
PAGE_SIZE = 100
MAX_PAGE = 10000


@frozen
class TripleWhaleEndpoint:
    path: str
    data_selector: str
    shop_field: str
    primary_keys: tuple[str, ...]
    partition_key: str
    sort_mode: SortMode | None
    window: Literal["month", "day"]
    scope: str
    description: str


ENDPOINTS = {
    "orders_with_journeys": TripleWhaleEndpoint(
        path="attribution/get-orders-with-journeys-v2",
        data_selector="ordersWithJourneys",
        shop_field="shop",
        primary_keys=("order_id",),
        partition_key="created_at",
        sort_mode=None,
        window="month",
        scope="Pixel Attribution",
        description="Orders with customer journeys and marketing attribution.",
    ),
    "summary_page": TripleWhaleEndpoint(
        path="summary-page/get-data",
        data_selector="metrics",
        shop_field="shopDomain",
        primary_keys=("date", "metricName"),
        partition_key="date",
        sort_mode="asc",
        window="day",
        scope="Summary Page",
        description="Daily summary metrics for sales and marketing performance.",
    ),
}

# Date filters lack account verification. Full refresh also captures changes to historical attribution and metrics.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
