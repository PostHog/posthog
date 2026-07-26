from dataclasses import dataclass
from typing import Literal, Optional

# The Cloud Billing API and the Cloud Billing Budgets API are separate services with
# separate hosts, but share the same auth, pagination and resource-name conventions.
CLOUD_BILLING_HOST = "https://cloudbilling.googleapis.com"
BILLING_BUDGETS_HOST = "https://billingbudgets.googleapis.com"

FanOut = Literal["billing_account", "service"]


@dataclass(frozen=True)
class GcpCloudBillingEndpointConfig:
    name: str
    host: str
    # `{parent}` is filled with the parent resource name for fan-out endpoints.
    path: str
    # Key the rows live under in the response body.
    data_key: str
    primary_key: list[str]
    # Google caps `pageSize` per method; requesting more than the cap is silently clamped.
    page_size: int
    fan_out: Optional[FanOut] = None
    # Column the parent resource name is written to on fan-out rows.
    parent_field: Optional[str] = None


# None of these entities expose an updated-since filter, so every table is a full refresh.
# Detailed cost and usage line items are not served by this API at all — they arrive through
# BigQuery billing export, which is the BigQuery source's job.
GCP_CLOUD_BILLING_ENDPOINTS: dict[str, GcpCloudBillingEndpointConfig] = {
    "billing_accounts": GcpCloudBillingEndpointConfig(
        name="billing_accounts",
        host=CLOUD_BILLING_HOST,
        path="/v1/billingAccounts",
        data_key="billingAccounts",
        primary_key=["name"],
        page_size=100,
    ),
    "projects": GcpCloudBillingEndpointConfig(
        name="projects",
        host=CLOUD_BILLING_HOST,
        path="/v1/{parent}/projects",
        data_key="projectBillingInfo",
        primary_key=["name"],
        page_size=100,
        fan_out="billing_account",
        parent_field="_billing_account_name",
    ),
    "sub_accounts": GcpCloudBillingEndpointConfig(
        name="sub_accounts",
        host=CLOUD_BILLING_HOST,
        path="/v1/{parent}/subAccounts",
        data_key="billingAccounts",
        primary_key=["name"],
        page_size=100,
        fan_out="billing_account",
        parent_field="_billing_account_name",
    ),
    "services": GcpCloudBillingEndpointConfig(
        name="services",
        host=CLOUD_BILLING_HOST,
        path="/v1/services",
        data_key="services",
        primary_key=["name"],
        page_size=5000,
    ),
    "skus": GcpCloudBillingEndpointConfig(
        name="skus",
        host=CLOUD_BILLING_HOST,
        path="/v1/{parent}/skus",
        data_key="skus",
        primary_key=["name"],
        page_size=5000,
        fan_out="service",
        parent_field="_service_name",
    ),
    "budgets": GcpCloudBillingEndpointConfig(
        name="budgets",
        host=BILLING_BUDGETS_HOST,
        path="/v1/{parent}/budgets",
        data_key="budgets",
        primary_key=["name"],
        page_size=100,
        fan_out="billing_account",
        parent_field="_billing_account_name",
    ),
}

ENDPOINTS = tuple(GCP_CLOUD_BILLING_ENDPOINTS.keys())
