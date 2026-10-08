from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField


@frozen
class YnabEndpoint:
    name: str
    path: str
    data_selector: str
    primary_keys: tuple[str, ...] = ("plan_id", "id")
    partition_key: str | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    page_size: int = 0
    fanout: DependentEndpointConfig | None = None


PLAN_FANOUT = DependentEndpointConfig(
    parent_name="plans",
    resolve_param="plan_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "plan_id"},
)

ENDPOINTS: dict[str, YnabEndpoint] = {
    "plans": YnabEndpoint(name="plans", path="plans", data_selector="data.plans", primary_keys=("id",)),
    "accounts": YnabEndpoint(
        name="accounts", path="plans/{plan_id}/accounts", data_selector="data.accounts", fanout=PLAN_FANOUT
    ),
    "categories": YnabEndpoint(
        name="categories",
        path="plans/{plan_id}/categories",
        data_selector="data.category_groups[*].categories[*]",
        fanout=PLAN_FANOUT,
    ),
    "category_groups": YnabEndpoint(
        name="category_groups",
        path="plans/{plan_id}/categories",
        data_selector="data.category_groups",
        fanout=PLAN_FANOUT,
    ),
    "payees": YnabEndpoint(
        name="payees", path="plans/{plan_id}/payees", data_selector="data.payees", fanout=PLAN_FANOUT
    ),
    "payee_locations": YnabEndpoint(
        name="payee_locations",
        path="plans/{plan_id}/payee_locations",
        data_selector="data.payee_locations",
        fanout=PLAN_FANOUT,
    ),
    "months": YnabEndpoint(
        name="months",
        path="plans/{plan_id}/months",
        data_selector="data.months",
        primary_keys=("plan_id", "month"),
        partition_key="month",
        fanout=PLAN_FANOUT,
    ),
    "transactions": YnabEndpoint(
        name="transactions",
        path="plans/{plan_id}/transactions",
        data_selector="data.transactions",
        fanout=DependentEndpointConfig(
            parent_name="plans",
            resolve_param="plan_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "plan_id"},
            # YNAB otherwise limits transaction listings to the last year.
            child_params={"since_date": "0001-01-01"},
        ),
    ),
    "scheduled_transactions": YnabEndpoint(
        name="scheduled_transactions",
        path="plans/{plan_id}/scheduled_transactions",
        data_selector="data.scheduled_transactions",
        fanout=PLAN_FANOUT,
    ),
}
