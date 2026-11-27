from dataclasses import field

from products.warehouse_sources.sources.sdk import frozen

BASE_URL = "https://api.yotpo.com/"
REQUEST_TIMEOUT = (10, 30)


@frozen
class YotpoEndpoint:
    path: str
    data_selector: str
    description: str
    primary_keys: tuple[str, ...] | None = None
    partition_key: str | None = None
    page_size_param: str | None = None
    # V3 Core lists page with an opaque `page_info` cursor instead of page numbers.
    cursor_pagination: bool = False
    email_date_range: bool = False
    params: dict[str, str] = field(default_factory=dict)
    token_query_param: str | None = None


# Timestamp filters have not been verified with an account, so every table uses full refresh.
ENDPOINTS: dict[str, YotpoEndpoint] = {
    "reviews": YotpoEndpoint(
        path="v1/apps/{app_key}/reviews",
        data_selector="reviews",
        description="Product and site reviews, including unpublished reviews.",
        primary_keys=("id",),
        partition_key="created_at",
        page_size_param="count",
        params={"deleted": "true"},
    ),
    "email_analytics": YotpoEndpoint(
        path="analytics/v1/emails/{app_key}/emails_sent",
        data_selector="date_series_points",
        description="Daily counts of review request emails sent, grouped by email type, from the configured start date.",
        primary_keys=("since", "until"),
        partition_key="since",
        email_date_range=True,
        params={"date_bucket": "day", "group_by": "email_type"},
        token_query_param="token",
    ),
    "raw_data": YotpoEndpoint(
        path="analytics/v1/emails/{app_key}/export/raw_data",
        data_selector="records",
        description="Email delivery and engagement records from the configured start date.",
        # The API exposes no unique email delivery ID, so a guessed key could discard records.
        primary_keys=None,
        partition_key="email_sent_timestamp",
        page_size_param="per_page",
        email_date_range=True,
        # The docs name sort directions but do not define their parameter values.
    ),
    "unsubscribers": YotpoEndpoint(
        path="apps/{app_key}/unsubscribers",
        data_selector="response.unsubscribers",
        description="Email addresses excluded from Yotpo review request emails.",
        primary_keys=("user_email", "email_type_id"),
        page_size_param="count",
    ),
    "orders": YotpoEndpoint(
        path="core/v3/stores/{app_key}/orders",
        data_selector="orders",
        description="Store orders with totals, payment status, customer, line items and fulfillments.",
        primary_keys=("yotpo_id",),
        partition_key="created_at",
        page_size_param="limit",
        cursor_pagination=True,
    ),
    "products": YotpoEndpoint(
        path="core/v3/stores/{app_key}/products",
        data_selector="products",
        description="The store's product catalog, as synced to Yotpo.",
        primary_keys=("yotpo_id",),
        partition_key="created_at",
        page_size_param="limit",
        cursor_pagination=True,
    ),
    "customers": YotpoEndpoint(
        path="core/v3/stores/{app_key}/customers",
        data_selector="customers",
        description="Store customers with their reviews and loyalty summaries.",
        # Customers created by email only have no external ID, and the API returns no Yotpo ID.
        primary_keys=None,
        page_size_param="limit",
        cursor_pagination=True,
    ),
    "customer_segments": YotpoEndpoint(
        path="core/v3/stores/{app_key}/profile_groups",
        data_selector="profileGroups",
        description="Customer segments and imported lists, with their rules and data sources.",
        primary_keys=("id",),
    ),
}
