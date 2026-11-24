from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, IncrementalFieldType

BASE_URL = "https://api.samcart.com"
API_VERSION = "v2"

# Documented maximum for every v2 list endpoint (the default is 25).
PAGE_SIZE = 100

# Every v2 list endpoint sorts by id only. Ascending gives a stable cursor walk from the oldest
# record. Ids are ULIDs, but SamCart does not document that their order matches `created_at`, so
# the responses do not claim a sort order on the incremental field.
SORT = "id"

PARTITION_KEY = "created_at"


@dataclass(frozen=True)
class SamCartEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    fanout: Optional[DependentEndpointConfig] = None
    page_size: int = PAGE_SIZE
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None


def _created_at_field() -> IncrementalField:
    return {
        "label": "created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "created_at",
        "field_type": IncrementalFieldType.DateTime,
    }


# The list endpoints filter only on `created_at` (`created_at_min`), so an incremental sync picks up
# new records and does not see later changes to older ones, such as a refund that changes the status
# of an order, charge or subscription. A full refresh reads those changes.
SAMCART_ENDPOINTS: dict[str, SamCartEndpointConfig] = {
    # The order list holds only a slim cart item summary and no attribution, so each listed order
    # is read again from the detail endpoint, which has the full line items and the UTM parameters.
    "order_list": SamCartEndpointConfig(name="order_list", path=f"/{API_VERSION}/orders"),
    "Orders": SamCartEndpointConfig(
        name="Orders",
        path=f"/{API_VERSION}/orders/{{id}}",
        fanout=DependentEndpointConfig(
            parent_name="order_list",
            resolve_param="id",
            resolve_field="id",
            include_from_parent=[],
        ),
        incremental_fields=[_created_at_field()],
        default_incremental_field="created_at",
    ),
    "Charges": SamCartEndpointConfig(
        name="Charges",
        path=f"/{API_VERSION}/charges",
        incremental_fields=[_created_at_field()],
        default_incremental_field="created_at",
    ),
    "Subscriptions": SamCartEndpointConfig(
        name="Subscriptions",
        path=f"/{API_VERSION}/subscriptions",
        incremental_fields=[_created_at_field()],
        default_incremental_field="created_at",
    ),
    "Refunds": SamCartEndpointConfig(
        name="Refunds",
        path=f"/{API_VERSION}/refunds",
        incremental_fields=[_created_at_field()],
        default_incremental_field="created_at",
    ),
}

ENDPOINTS = ("Orders", "Charges", "Subscriptions", "Refunds")

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: SAMCART_ENDPOINTS[name].incremental_fields for name in ENDPOINTS
}
