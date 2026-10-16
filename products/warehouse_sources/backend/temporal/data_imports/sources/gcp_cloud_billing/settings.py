from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import PartitionMode
from products.warehouse_sources.backend.types import IncrementalField

CLOUD_BILLING_URL = "https://cloudbilling.googleapis.com/"
BUDGETS_URL = "https://billingbudgets.googleapis.com/"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPES = ("https://www.googleapis.com/auth/cloud-billing",)


@frozen
class BillingEndpoint:
    name: str
    path: str
    data_selector: str
    page_size: int = 100
    primary_keys: tuple[str, ...] = ("name",)
    partition_keys: tuple[str, ...] = ("name",)
    partition_mode: PartitionMode = "md5"
    partition_count: int = 16
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    fanout: DependentEndpointConfig | None = None


ENDPOINTS = {
    "billing_accounts": BillingEndpoint(
        name="billing_accounts", path="v1/billingAccounts", data_selector="billingAccounts"
    ),
    "projects": BillingEndpoint(
        name="projects",
        path="v1/{parent}/projects",
        data_selector="projectBillingInfo",
        fanout=DependentEndpointConfig(
            parent_name="billing_accounts",
            resolve_param="parent",
            resolve_field="name",
            include_from_parent=["name"],
            parent_field_renames={"name": "parent_billing_account"},
        ),
    ),
    "sub_accounts": BillingEndpoint(
        name="sub_accounts",
        path="v1/{parent}/subAccounts",
        data_selector="billingAccounts",
        fanout=DependentEndpointConfig(
            parent_name="billing_accounts",
            resolve_param="parent",
            resolve_field="name",
            include_from_parent=["name"],
            parent_field_renames={"name": "parent_billing_account"},
        ),
    ),
    "services": BillingEndpoint(name="services", path="v1/services", data_selector="services", page_size=1000),
    "skus": BillingEndpoint(
        name="skus",
        path="v1/{parent}/skus",
        data_selector="skus",
        page_size=1000,
        fanout=DependentEndpointConfig(
            parent_name="services",
            resolve_param="parent",
            resolve_field="name",
            include_from_parent=["name"],
            parent_field_renames={"name": "parent_service"},
        ),
    ),
    "budgets": BillingEndpoint(
        name="budgets",
        path=f"{BUDGETS_URL}v1/{{parent}}/budgets",
        data_selector="budgets",
        fanout=DependentEndpointConfig(
            parent_name="billing_accounts",
            resolve_param="parent",
            resolve_field="name",
            include_from_parent=["name"],
            parent_field_renames={"name": "parent_billing_account"},
        ),
    ),
}

# SKU pricing windows must stay within one calendar month, so they cannot track general updates.
# These request shapes follow Google's discovery specifications and need verification with a live account.
INCREMENTAL_FIELDS = {name: endpoint.incremental_fields for name, endpoint in ENDPOINTS.items()}
