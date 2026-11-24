from typing import NotRequired, TypedDict

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, incremental_field

API_VERSION = "v1"
BASE_URL = f"https://api.trustradius.com/{API_VERSION}"
API_DOCS_URL = "https://apidocs.trustradius.com/docs/public-api/YXBpOjUxMzgzNjA-trust-radius-api"


class EndpointConfig(TypedDict):
    path: str
    data_selector: str
    primary_keys: list[str]
    partition_key: str | None
    # Report endpoints take a date range and page with `skip` and `limit`.
    report: NotRequired[bool]
    # Fields the request sorts by, so that `skip` paging is stable.
    sort: NotRequired[str]
    requires_products: NotRequired[bool]


ENDPOINTS: dict[str, EndpointConfig] = {
    "products": {
        "path": "product-ids",
        "data_selector": "",
        "primary_keys": ["_id"],
        "partition_key": None,
    },
    "product_scores": {
        "path": "product-scores",
        "data_selector": "products",
        "primary_keys": ["id"],
        "partition_key": None,
    },
    "trustquotes": {
        "path": "trustquotes",
        "data_selector": "",
        "primary_keys": ["id"],
        "partition_key": "created",
    },
    "tags": {
        "path": "tags",
        "data_selector": "",
        "primary_keys": ["id"],
        "partition_key": None,
    },
    "traffic_products": {
        "path": "reports/traffic/products",
        "data_selector": "",
        "primary_keys": ["date", "productId", "categoryId"],
        "partition_key": "date",
        "report": True,
        "sort": "date,productId,categoryId",
        "requires_products": True,
    },
    "visitor_insights_companies": {
        "path": "reports/visitor-insights/companies",
        "data_selector": "",
        "primary_keys": ["date", "productId", "companyName"],
        "partition_key": "date",
        "report": True,
        "sort": "date,productId,companyName",
    },
    "visitor_insights_pages": {
        "path": "reports/visitor-insights/pages",
        "data_selector": "",
        "primary_keys": ["date", "productId", "companyName", "url"],
        "partition_key": "date",
        "report": True,
        "sort": "date,productId,companyName,url",
    },
    "intent": {
        "path": "intent",
        "data_selector": "accounts",
        "primary_keys": ["id", "date"],
        "partition_key": "date",
    },
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "traffic_products": [incremental_field("date")],
    "visitor_insights_companies": [incremental_field("date")],
    "visitor_insights_pages": [incremental_field("date")],
    "intent": [incremental_field("date", IncrementalFieldType.Date)],
}

# Recent report days can change after their first import, so incremental runs read them again.
INCREMENTAL_LOOKBACK_SECONDS = dict.fromkeys(INCREMENTAL_FIELDS, 2 * 24 * 60 * 60)

REPORT_PAGE_SIZE = 1000
# The reports document no retention, so a first sync reads one year of daily rows.
REPORT_HISTORY_DAYS = 365
# The intent API serves at most the 45 days before today.
INTENT_HISTORY_DAYS = 44
PRODUCT_IDS_PER_REQUEST = 50

AUTH_ERROR = "TrustRadius rejected your API key. Check the key with your TrustRadius Client Success Manager."
PERMISSION_ERROR = (
    "TrustRadius denied access. Ask your Client Success Manager to check your API license and permissions."
)
NON_RETRYABLE_ERRORS = {
    "401 Client Error": AUTH_ERROR,
    "403 Client Error": PERMISSION_ERROR,
}
