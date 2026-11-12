from dataclasses import field

from products.warehouse_sources.sources.sdk import (
    DependentEndpointConfig,
    IncrementalField,
    IncrementalFieldType,
    frozen,
)


@frozen
class StiggEndpointConfig:
    name: str
    path: str
    # Most Stigg object IDs (customer/subscription/feature slugs) are unique across the
    # environment the API key scopes to, so `id` is a safe default primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation timestamp used for datetime partitioning. `createdAt` is a required
    # field on every list DTO in Stigg's OpenAPI spec and never changes after creation.
    # None for a table whose rows carry no creation timestamp.
    partition_key: str | None = "createdAt"
    page_size: int = 100
    # None for a child endpoint whose spec documents no page-size param.
    page_size_param: str | None = "limit"
    data_selector: str = "data"
    # False for a child endpoint that returns one unpaginated response per parent.
    paginated: bool = True
    fanout: DependentEndpointConfig | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None


# Plans and addons are versioned, so their listings can return one row per version of the same
# package. The sub-resource paths take only the package id, so the parent filter in `stigg.py`
# sends one request per id.
_PLAN_FANOUT = DependentEndpointConfig(
    parent_name="plans",
    resolve_param="plan_id",
    resolve_field="pathId",
    include_from_parent=["id"],
    parent_field_renames={"id": "planId"},
    parent_params={"limit": 100},
)

_ADDON_FANOUT = DependentEndpointConfig(
    parent_name="addons",
    resolve_param="addon_id",
    resolve_field="pathId",
    include_from_parent=["id"],
    parent_field_renames={"id": "addonId"},
    parent_params={"limit": 100},
)

_CUSTOMER_FANOUT = DependentEndpointConfig(
    parent_name="customers",
    resolve_param="customer_id",
    resolve_field="pathId",
    include_from_parent=["id"],
    parent_field_renames={"id": "customerId"},
    parent_params={"limit": 100},
)


# Stigg REST API (https://api.stigg.io/api/v1) list endpoints. All but the credit ledger are
# full refresh only: the list endpoints expose a server-side `createdAt` range filter but no
# updated-since filter, and billing objects (subscriptions, plans, customers) mutate in place —
# syncing incrementally on creation time would permanently miss those updates, so we do not
# advertise it. Change capture on Stigg's side is webhook/queue based, with manual setup
# only (no programmatic webhook management API).
STIGG_ENDPOINTS: dict[str, StiggEndpointConfig] = {
    "customers": StiggEndpointConfig(name="customers", path="/customers"),
    "subscriptions": StiggEndpointConfig(name="subscriptions", path="/subscriptions"),
    "products": StiggEndpointConfig(name="products", path="/products"),
    # Plans and addons are versioned packages: `id` is the package slug shared by every
    # version, so the composite key with `versionNumber` keeps rows unique table-wide.
    "plans": StiggEndpointConfig(
        name="plans",
        path="/plans",
        primary_keys=["id", "versionNumber"],
    ),
    "addons": StiggEndpointConfig(
        name="addons",
        path="/addons",
        primary_keys=["id", "versionNumber"],
    ),
    "features": StiggEndpointConfig(name="features", path="/features"),
    "coupons": StiggEndpointConfig(name="coupons", path="/coupons"),
    # The spec documents no page-size or cursor params here, but the response carries the
    # standard `pagination` envelope, so the cursor paginator still follows a `next` cursor.
    "plan_entitlements": StiggEndpointConfig(
        name="plan_entitlements",
        path="/plans/{plan_id}/entitlements",
        primary_keys=["planId", "id"],
        page_size_param=None,
        fanout=_PLAN_FANOUT,
    ),
    "plan_charges": StiggEndpointConfig(
        name="plan_charges",
        path="/plans/{plan_id}/charges",
        primary_keys=["planId", "id"],
        fanout=_PLAN_FANOUT,
    ),
    "plan_overage_charges": StiggEndpointConfig(
        name="plan_overage_charges",
        path="/plans/{plan_id}/overage-charges",
        primary_keys=["planId", "id"],
        fanout=_PLAN_FANOUT,
    ),
    "addon_charges": StiggEndpointConfig(
        name="addon_charges",
        path="/addons/{addon_id}/charges",
        primary_keys=["addonId", "id"],
        fanout=_ADDON_FANOUT,
    ),
    # `customerId` is a required filter. Without `resourceId` the API returns only the grants
    # that are not scoped to a resource.
    "credit_grants": StiggEndpointConfig(
        name="credit_grants",
        path="/credits/grants?customerId={customer_id}",
        primary_keys=["customerId", "id"],
        fanout=_CUSTOMER_FANOUT,
    ),
    # Ledger events are immutable and filter server-side on `startDate` (inclusive), so the table
    # can sync incrementally. Rows carry no id and several fields are null for some event types, so
    # the key is every field that can tell two events apart (the merge matches nulls as equal).
    "credit_ledger": StiggEndpointConfig(
        name="credit_ledger",
        path="/credits/ledger?customerId={customer_id}",
        primary_keys=[
            "customerId",
            "creditCurrencyId",
            "creditGrantId",
            "eventType",
            "timestamp",
            "eventId",
            "featureId",
            "reservationId",
            "resourceId",
        ],
        partition_key="timestamp",
        fanout=_CUSTOMER_FANOUT,
        incremental_fields=[
            IncrementalField(
                label="timestamp",
                type=IncrementalFieldType.DateTime,
                field="timestamp",
                field_type=IncrementalFieldType.DateTime,
            )
        ],
        default_incremental_field="timestamp",
    ),
    # One unpaginated state object per customer. Rows carry no id or creation time, so the key
    # is the feature or the credit currency that `stigg.py` lifts to the row root.
    "customer_entitlements": StiggEndpointConfig(
        name="customer_entitlements",
        path="/customers/{customer_id}/entitlements",
        primary_keys=["customerId", "type", "featureId", "currencyId"],
        partition_key=None,
        data_selector="data.entitlements",
        page_size_param=None,
        paginated=False,
        fanout=_CUSTOMER_FANOUT,
    ),
}

ENDPOINTS = tuple(STIGG_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in STIGG_ENDPOINTS.items() if config.incremental_fields
}
