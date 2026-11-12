from dataclasses import field
from enum import StrEnum
from typing import Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, ResponseAction, frozen

PRODUCTION_BASE_URL = "https://api.creem.io"
TEST_BASE_URL = "https://test-api.creem.io"

# The documented default for the larger listings. The spec gives no maximum for `page_size`, so a
# bigger value is untested.
PAGE_NUMBER_PAGE_SIZE = 50
# Documented maximum of `limit` on the cursor listings.
CURSOR_PAGE_SIZE = 100


class CreemEnvironment(StrEnum):
    PRODUCTION = "production"
    TEST = "test"


class CreemPagination(StrEnum):
    # `page_number`/`page_size` params, rows under `items`, and a `pagination.next_page` body field.
    PAGE_NUMBER = "page_number"
    # `limit`/`starting_after` params, rows under `data`, and a `has_more` body flag.
    CURSOR = "cursor"


@frozen
class CreemEndpointConfig:
    name: str
    path: str
    pagination: CreemPagination = CreemPagination.PAGE_NUMBER
    params: dict[str, str] = field(default_factory=dict)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # An ISO 8601 creation time. Endpoints that send it as a number are left unpartitioned.
    partition_key: Optional[str] = None
    fanout: Optional[DependentEndpointConfig] = None
    # No Creem list endpoint filters on an update time, so every endpoint is a full refresh.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    page_size: int = PAGE_NUMBER_PAGE_SIZE

    @property
    def page_size_param(self) -> str:
        return "page_size" if self.pagination == CreemPagination.PAGE_NUMBER else "limit"

    @property
    def data_selector(self) -> str:
        return "items" if self.pagination == CreemPagination.PAGE_NUMBER else "data"


_DELETED_CUSTOMER_IGNORE: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}]

# Licenses have no store-wide listing. Each customer's licenses come from its own endpoint.
_LICENSES_FANOUT = DependentEndpointConfig(
    parent_name="Customers",
    resolve_param="customer_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "customer_id"},
    # A customer deleted between the customer listing and the license fetch drops out of the sync.
    child_response_actions=_DELETED_CUSTOMER_IGNORE,
)

CREEM_ENDPOINTS: dict[str, CreemEndpointConfig] = {
    config.name: config
    for config in (
        CreemEndpointConfig(name="Products", path="/v1/products/search", partition_key="created_at"),
        CreemEndpointConfig(name="Customers", path="/v1/customers/list", partition_key="created_at"),
        CreemEndpointConfig(name="Subscriptions", path="/v1/subscriptions/search", partition_key="created_at"),
        CreemEndpointConfig(name="Transactions", path="/v1/transactions/search"),
        CreemEndpointConfig(name="Discounts", path="/v1/discounts/search"),
        CreemEndpointConfig(
            name="Licenses",
            path="/v1/customers/{customer_id}/licenses",
            primary_keys=["customer_id", "id"],
            partition_key="created_at",
            fanout=_LICENSES_FANOUT,
        ),
        CreemEndpointConfig(name="Affiliates", path="/v1/affiliates"),
        CreemEndpointConfig(name="AffiliateInvites", path="/v1/affiliates/invites"),
        CreemEndpointConfig(name="Splits", path="/v1/splits"),
        CreemEndpointConfig(
            name="Meters",
            path="/v1/meters",
            pagination=CreemPagination.CURSOR,
            # Archived meters are hidden by default.
            params={"include_archived": "true"},
            partition_key="created_at",
            page_size=CURSOR_PAGE_SIZE,
        ),
        CreemEndpointConfig(
            name="UsageEvents",
            path="/v1/events",
            pagination=CreemPagination.CURSOR,
            partition_key="created_at",
            page_size=CURSOR_PAGE_SIZE,
        ),
        CreemEndpointConfig(
            name="CreditAccounts",
            path="/v1/customer-credits/accounts",
            pagination=CreemPagination.CURSOR,
            partition_key="created_at",
            page_size=CURSOR_PAGE_SIZE,
        ),
    )
}

ENDPOINTS = tuple(CREEM_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
