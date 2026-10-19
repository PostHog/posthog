from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Rippling list pages cap at 100 items.
PAGE_SIZE = 100

# Every Rippling REST list endpoint supports the same standard query params
# (cursor/limit pagination, OData-style `filter`, `order_by` on id/created_at/
# updated_at), so the incremental menu is shared.
_UPDATED_AT_INCREMENTAL_FIELD: IncrementalField = {
    "label": "updated_at",
    "type": IncrementalFieldType.DateTime,
    "field": "updated_at",
    "field_type": IncrementalFieldType.DateTime,
}

_STANDARD_INCREMENTAL_FIELDS: list[IncrementalField] = [
    _UPDATED_AT_INCREMENTAL_FIELD,
    {
        "label": "created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "created_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@frozen
class RipplingEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(_STANDARD_INCREMENTAL_FIELDS))
    # Stable creation-time field used for datetime partitioning. Never an
    # updated_at-style field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    # Full-refresh sort field. Must be one of the endpoint's documented sortable fields; None for
    # endpoints that accept no `order_by`.
    order_by: Optional[str] = "created_at"
    fanout: Optional[DependentEndpointConfig] = None
    page_size: int = PAGE_SIZE

    @property
    def default_incremental_field(self) -> Optional[str]:
        return self.incremental_fields[0]["field"] if self.incremental_fields else None


RIPPLING_ENDPOINTS: dict[str, RipplingEndpointConfig] = {
    "workers": RipplingEndpointConfig(
        name="workers",
        path="/workers",
        partition_key="created_at",
    ),
    "users": RipplingEndpointConfig(
        name="users",
        path="/users",
        partition_key="created_at",
    ),
    "companies": RipplingEndpointConfig(
        name="companies",
        path="/companies",
    ),
    "departments": RipplingEndpointConfig(
        name="departments",
        path="/departments",
    ),
    "teams": RipplingEndpointConfig(
        name="teams",
        path="/teams",
    ),
    "levels": RipplingEndpointConfig(
        name="levels",
        path="/levels",
    ),
    "work_locations": RipplingEndpointConfig(
        name="work_locations",
        path="/work-locations",
    ),
    "employment_types": RipplingEndpointConfig(
        name="employment_types",
        path="/employment-types",
    ),
    "compensations": RipplingEndpointConfig(
        name="compensations",
        path="/compensations",
        partition_key="created_at",
    ),
    # Variable compensation payouts accept no OData filter and no order_by, so full refresh only.
    "variable_compensation_payouts": RipplingEndpointConfig(
        name="variable_compensation_payouts",
        path="/variable-compensation-payouts",
        incremental_fields=[],
        partition_key="created_at",
        order_by=None,
    ),
    # Time entries filter on updated_at but not on created_at.
    "time_entries": RipplingEndpointConfig(
        name="time_entries",
        path="/time-entries",
        incremental_fields=[_UPDATED_AT_INCREMENTAL_FIELD],
        partition_key="created_at",
    ),
    # Leave requests filter on neither created_at nor updated_at, so full refresh only.
    "leave_requests": RipplingEndpointConfig(
        name="leave_requests",
        path="/leave-requests",
        incremental_fields=[],
        partition_key="created_at",
    ),
    # Payroll runs carry no created_at/updated_at, accept no filter, and sort only on check_date.
    "payroll_runs": RipplingEndpointConfig(
        name="payroll_runs",
        path="/payroll-runs",
        incremental_fields=[],
        order_by="check_date",
    ),
    "worker_payroll_records": RipplingEndpointConfig(
        name="worker_payroll_records",
        path="/payroll-runs/{run_id}/worker-payroll-records",
        primary_keys=["run_id", "id"],
        incremental_fields=[],
        order_by=None,
        fanout=DependentEndpointConfig(
            parent_name="payroll_runs",
            resolve_param="run_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "run_id"},
            parent_params={"order_by": "check_date"},
        ),
    ),
}

ENDPOINTS = tuple(RIPPLING_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in RIPPLING_ENDPOINTS.items() if config.incremental_fields
}
