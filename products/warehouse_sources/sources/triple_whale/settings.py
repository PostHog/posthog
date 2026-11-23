from typing import Literal

from products.warehouse_sources.sources.sdk import IncrementalField, SortMode, frozen

API_ROOT = "https://api.triplewhale.com/api"
PAGE_SIZE = 100
MAX_PAGE = 10000
SQL_PATH = "orcabase/api/sql"
SQL_PAGE_SIZE = 1000


@frozen
class TripleWhaleEndpoint:
    path: str
    data_selector: str
    shop_field: str
    primary_keys: tuple[str, ...]
    partition_key: str | None
    sort_mode: SortMode | None
    # "all" reads a table that has no event_date in one window.
    window: Literal["month", "day", "all"]
    scope: str | None
    description: str
    # Tables read through the custom SQL endpoint. The data dictionary advises against SELECT *.
    sql: str | None = None


def sql_endpoint(
    sql: str,
    primary_keys: tuple[str, ...],
    partition_key: str | None,
    window: Literal["month", "all"],
    description: str,
) -> TripleWhaleEndpoint:
    return TripleWhaleEndpoint(
        path=SQL_PATH,
        data_selector="data",
        shop_field="shopId",
        primary_keys=primary_keys,
        partition_key=partition_key,
        sort_mode=None,
        window=window,
        scope=None,
        description=description,
        sql=" ".join(sql.split()),
    )


ORDERS_SQL = """
SELECT o.order_id, o.order_name, o.platform, o.shop_id, o.event_date, o.event_hour, o.created_at, o.cancelled_at,
    o.currency, o.currency_rate, o.customer_id, o.customer_id_key, o.customer_email, o.customer_first_name,
    o.customer_last_name, o.customer_tags, o.is_new_customer, o.is_subscription_order,
    o.is_first_order_in_subscription, o.source_name, o.tags, o.discount_code, o.discount_type,
    o.fulfillment_status, o.billing_country_code, o.shipping_city, o.shipping_state_code, o.shipping_zip,
    o.shipping_country_code, o.order_revenue, o.gross_product_sales, o.discount_amount, o.refund_money, o.taxes,
    o.shipping_price, o.shipping_costs, o.cost_of_goods, o.payment_gateway_costs, o.handling_fees,
    o.product_quantity_sold_in_order, o.products_info
FROM orders_table o
WHERE o.event_date BETWEEN @startDate AND @endDate
ORDER BY o.event_date, o.platform, o.order_id
"""

# Rows are summed to one row per ad, day and breakdown, so the primary key is unique. Facebook breakdown rows stay
# separate from the ad totals through breakdown_dimension and breakdown_value.
ADS_SQL = """
SELECT a.event_date, a.channel, a.account_id, a.campaign_id, a.adset_id, a.ad_id, a.breakdown_dimension,
    a.breakdown_value, any(a.account_name) AS account_name, any(a.campaign_name) AS campaign_name,
    any(a.adset_name) AS adset_name, any(a.ad_name) AS ad_name, any(a.campaign_status) AS campaign_status,
    any(a.adset_status) AS adset_status, any(a.ad_status) AS ad_status, any(a.currency) AS currency,
    sum(a.spend) AS spend, sum(a.impressions) AS impressions, sum(a.clicks) AS clicks,
    sum(a.outbound_clicks) AS outbound_clicks, sum(a.conversions) AS conversions,
    sum(a.conversion_value) AS conversion_value, sum(a.all_conversions) AS all_conversions,
    sum(a.all_conversion_value) AS all_conversion_value, sum(a.onsite_purchases) AS onsite_purchases,
    sum(a.onsite_conversion_value) AS onsite_conversion_value, sum(a.visits) AS visits,
    sum(a.engagements) AS engagements, sum(a.total_video_view) AS total_video_view, sum(a.thruplays) AS thruplays
FROM ads_table a
WHERE a.event_date BETWEEN @startDate AND @endDate
GROUP BY a.event_date, a.channel, a.account_id, a.campaign_id, a.adset_id, a.ad_id, a.breakdown_dimension,
    a.breakdown_value
ORDER BY a.event_date, a.channel, a.account_id, a.campaign_id, a.adset_id, a.ad_id, a.breakdown_dimension,
    a.breakdown_value
"""

CUSTOMERS_SQL = """
SELECT c.platform, c.customer_id, c.customer_id_key, c.created_at, c.status, c.email_address, c.first_name,
    c.last_name, c.display_name, c.phone, c.city, c.state, c.state_code, c.zip, c.country, c.country_code,
    c.locale, c.customer_tags, c.last_order_id, c.tax_exempt, c.verified_email_address,
    c.email_marketing_consent_status, c.email_marketing_consent_opt_in_level,
    c.email_marketing_consent_updated_at, c.sms_marketing_consent_opt_in_level,
    c.sms_marketing_consent_updated_at, c.product_subscriber_status, c.amount_spent, c.orders
FROM customers_table c
ORDER BY c.platform, c.customer_id
"""

PRODUCTS_SQL = """
SELECT p.platform, p.product_id, p.shop_id, p.integration_id, p.product_name, p.product_type, p.product_status,
    p.vendor, p.product_tags, p.collections, p.product_image_url, p.product_description,
    p.product_inventory_quantity, p.amazon_marketplace_id, p.variants
FROM products_table p
ORDER BY p.platform, p.product_id
"""


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
    "orders": sql_endpoint(
        ORDERS_SQL,
        primary_keys=("platform", "order_id"),
        partition_key="event_date",
        window="month",
        description="One row per order from every connected sales platform, with revenue, discounts and products.",
    ),
    "ads": sql_endpoint(
        ADS_SQL,
        primary_keys=(
            "event_date",
            "channel",
            "account_id",
            "campaign_id",
            "adset_id",
            "ad_id",
            "breakdown_dimension",
            "breakdown_value",
        ),
        partition_key="event_date",
        window="month",
        description="Daily ad spend and performance reported by each connected ad platform.",
    ),
    "customers": sql_endpoint(
        CUSTOMERS_SQL,
        primary_keys=("platform", "customer_id"),
        partition_key="created_at",
        window="all",
        description="Customer profiles from sales and email/SMS platforms, with lifetime spend and order count.",
    ),
    "products": sql_endpoint(
        PRODUCTS_SQL,
        primary_keys=("platform", "product_id"),
        partition_key=None,
        window="all",
        description="Product catalog from the sales platform, with variants and inventory.",
    ),
}

# Date filters lack account verification. Full refresh also captures changes to historical attribution and metrics.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
