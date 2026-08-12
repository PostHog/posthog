from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField

OKENDO_BASE_URL = "https://api.okendo.io/enterprise"
# Okendo's Merchant REST API is date-versioned and rejects requests without this header.
OKENDO_API_VERSION = "2025-02-01"
# The API caps `limit` at 100 and defaults to 25.
PAGE_LIMIT = 100

# `/reviews` returns only approved reviews unless `status` is set, so each status is fetched in
# turn and merged into one table with `status` as a column.
REVIEW_STATUSES = ("approved", "pending", "rejected")


@dataclass
class OkendoEndpointConfig:
    path: str
    # Key holding the row array in the response body.
    data_selector: str
    primary_keys: list[str]
    # Endpoints that accept `limit`/`lastEvaluated` and return a `nextUrl` cursor. The loyalty rule
    # catalogs document neither, so they are read as a single page.
    paginated: bool = True
    # Extra query params sent on every request for this endpoint.
    params: dict[str, str] = field(default_factory=dict)
    # One request per status value, merged into a single table. Empty for endpoints with no fan-out.
    statuses: tuple[str, ...] = ()
    # Stable creation timestamp to partition on, when the rows carry one.
    partition_key: str | None = None


OKENDO_ENDPOINTS: dict[str, OkendoEndpointConfig] = {
    "reviews": OkendoEndpointConfig(
        path="/reviews",
        data_selector="reviews",
        primary_keys=["reviewId"],
        # Default order is 'date desc', which shifts pages as new reviews land mid-sync. Ascending
        # order appends new rows past the cursor instead, so a page boundary can't skip a row.
        params={"orderBy": "date asc"},
        statuses=REVIEW_STATUSES,
        partition_key="dateCreated",
    ),
    "loyalty_earning_rules": OkendoEndpointConfig(
        path="/loyalty/earning_rules",
        data_selector="rules",
        # Earning rules carry no id; the documented schema is one rule per `type` variant.
        primary_keys=["type"],
        paginated=False,
    ),
    "loyalty_redemption_rules": OkendoEndpointConfig(
        path="/loyalty/redemption_rules",
        data_selector="rules",
        primary_keys=["redemptionRuleId"],
        paginated=False,
    ),
}

ENDPOINTS = tuple(OKENDO_ENDPOINTS.keys())

# Empty: no Okendo list endpoint exposes a created-since / updated-since filter, so there is no
# server-side watermark to sync against and every stream is full refresh. `build_endpoint_schemas`
# reads a missing entry as non-incremental.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
