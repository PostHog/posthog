from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PabblyEndpointConfig:
    name: str
    # Path under /api/v1. Fan-out child paths contain a "{parent_id}" placeholder.
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field to partition by. None when the resource has no createdAt.
    partition_key: Optional[str] = "createdAt"
    # Fan-out: name of the parent endpoint whose ids fill "{parent_id}" in `path`.
    parent: Optional[str] = None
    # Fan-out: column carrying the parent id on child rows. Most child objects already include
    # it (e.g. transactions carry customer_id); we inject it when the API omits it so the
    # composite primary key is always populated.
    parent_field: Optional[str] = None
    # Pabbly answers some endpoints with a 400 or a {"status": "error", "message": "No X found"}
    # envelope when there is simply no data (its Airbyte connector ignores those the same way).
    # When True, such responses are treated as an empty page instead of an error.
    ignore_no_data_errors: bool = False
    # HTTP sample capture stores raw response bodies as diagnostic artifacts. Set False on
    # endpoints whose bodies carry redeemable secrets the name-based scrubbers can't recognise
    # (e.g. the raw license codes in a licenses batch); requests stay metered and logged.
    capture_http_samples: bool = True


# Pabbly Subscription Billing REST endpoints (https://apidocs.pabbly.com/pabbly/subscription-billing).
# All are full refresh only: the API exposes no documented server-side created/updated-after
# filter, so there is no incremental cursor to advance (its Airbyte connector is likewise
# full-refresh only across every stream).
#
# Pabbly ids look globally unique (Mongo-style object ids), but the docs don't guarantee it, so
# fan-out children key on (parent id, id) to stay unique table-wide.
PABBLY_ENDPOINTS: dict[str, PabblyEndpointConfig] = {
    "customers": PabblyEndpointConfig(name="customers", path="/customers"),
    "subscriptions": PabblyEndpointConfig(name="subscriptions", path="/subscriptions"),
    "invoices": PabblyEndpointConfig(name="invoices", path="/invoices"),
    "products": PabblyEndpointConfig(name="products", path="/products", ignore_no_data_errors=True),
    "multiplans": PabblyEndpointConfig(name="multiplans", path="/multiplans"),
    "payment_gateways": PabblyEndpointConfig(name="payment_gateways", path="/paymentgateways"),
    "addons": PabblyEndpointConfig(
        name="addons",
        path="/addons/{parent_id}",
        primary_keys=["product_id", "id"],
        parent="products",
        parent_field="product_id",
        ignore_no_data_errors=True,
    ),
    "addon_list_category": PabblyEndpointConfig(
        name="addon_list_category",
        path="/addonlistcategory/{parent_id}",
        primary_keys=["product_id", "id"],
        # Addon categories expose no createdAt to partition by.
        partition_key=None,
        parent="products",
        parent_field="product_id",
        ignore_no_data_errors=True,
    ),
    "coupons": PabblyEndpointConfig(
        name="coupons",
        path="/coupon/{parent_id}",
        primary_keys=["product_id", "id"],
        parent="products",
        parent_field="product_id",
        ignore_no_data_errors=True,
        # coupon_code values are redeemable discounts; keep raw bodies out of captured HTTP samples.
        capture_http_samples=False,
    ),
    "licenses": PabblyEndpointConfig(
        name="licenses",
        path="/products/{parent_id}/licenses",
        primary_keys=["product_id", "id"],
        parent="products",
        parent_field="product_id",
        ignore_no_data_errors=True,
        # license_codes are redeemable secrets; keep raw bodies out of captured HTTP samples.
        capture_http_samples=False,
    ),
    "payment_methods": PabblyEndpointConfig(
        name="payment_methods",
        path="/paymentmethods/{parent_id}",
        primary_keys=["customer_id", "id"],
        parent="customers",
        parent_field="customer_id",
        ignore_no_data_errors=True,
    ),
    "refunds": PabblyEndpointConfig(
        name="refunds",
        path="/refund/{parent_id}",
        primary_keys=["customer_id", "id"],
        parent="customers",
        parent_field="customer_id",
        ignore_no_data_errors=True,
    ),
    "transactions": PabblyEndpointConfig(
        name="transactions",
        path="/transactions/{parent_id}",
        primary_keys=["customer_id", "id"],
        parent="customers",
        parent_field="customer_id",
        ignore_no_data_errors=True,
    ),
}

ENDPOINTS = tuple(PABBLY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
