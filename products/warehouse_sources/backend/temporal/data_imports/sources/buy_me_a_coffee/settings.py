from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

API_BASE_URL = "https://developers.buymeacoffee.com/api/v1"
API_DOCS_URL = "https://developers.buymeacoffee.com/#/apireference"


@frozen
class BuyMeACoffeeEndpointConfig:
    path: str
    primary_key: str
    partition_key: str
    incremental_fields: tuple[IncrementalField, ...] = ()
    status: str | None = None


# The API has no timestamp filter, so updates and refunds need a full refresh.
ENDPOINTS: dict[str, BuyMeACoffeeEndpointConfig] = {
    "supporters": BuyMeACoffeeEndpointConfig(
        path="supporters", primary_key="support_id", partition_key="support_created_on"
    ),
    "subscriptions": BuyMeACoffeeEndpointConfig(
        path="subscriptions",
        primary_key="subscription_id",
        partition_key="subscription_created_on",
        status="all",
    ),
    "extras": BuyMeACoffeeEndpointConfig(path="extras", primary_key="purchase_id", partition_key="purchased_on"),
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: list(endpoint.incremental_fields) for name, endpoint in ENDPOINTS.items()
}
