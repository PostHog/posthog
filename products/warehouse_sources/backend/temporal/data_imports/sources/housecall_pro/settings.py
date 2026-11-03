from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# The vendor's own default is 10; raising it cuts round trips against an undisclosed rate limit.
# Pagination termination reads `total_pages` from the body, so a smaller honored page size still
# walks every page correctly.
PAGE_SIZE = 100


@dataclass(frozen=False)  # static endpoint catalog, never mutated after construction
class HousecallProEndpointConfig:
    name: str
    path: str
    # Key the list lives under in the JSON envelope, e.g. {"customers": [...], "total_pages": N}.
    response_key: str
    incremental_fields: list[IncrementalField]
    # Stable datetime field used for datetime partitioning. Left unset for resources we have no
    # confirmed created_at field for (employees).
    partition_key: Optional[str] = None
    # Field passed to the API's `sort_by` param (ascending) and, for the incremental endpoint, the
    # field the `created_at_min` server-side filter narrows on. Only set where the vendor docs
    # confirm the field exists on the resource — left unset elsewhere rather than guessed, since an
    # unsupported `sort_by` value could 400 every page of the sync.
    sort_field: Optional[str] = None
    # Query param name for a genuine server-side timestamp filter, if the endpoint documents one.
    incremental_param: Optional[str] = None
    supports_incremental: bool = False
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    page_size: int = PAGE_SIZE
    default_incremental_field: Optional[str] = None
    # Set for resources only listed per job; the jobs list is re-read each sync.
    fanout: Optional[DependentEndpointConfig] = None
    # Values of the required `resource_type` query param. The table reads each value in turn and
    # stores it on the row as `resource_type`.
    resource_types: tuple[str, ...] = ()


# Housecall Pro REST API (https://api.housecallpro.com). Every list endpoint supports page-number
# pagination (`page`, `page_size`) and reports `total_pages` in the body. The per-job endpoints
# (appointments, line items) are the exception: they return the whole list in one body.
#
# Only Invoices documents a genuine server-side timestamp filter (`created_at_min`), so it's the
# only endpoint marked incremental. The others (Customers, Jobs, Estimates, Leads) accept
# `sort_by`/`sort_direction` generically per the vendor docs, but don't expose a filter that
# narrows the result set to "changed since X" — enabling incremental sync on those would still walk
# every page each run, which isn't a real incremental sync. Employees has neither a confirmed
# timestamp field nor a documented filter, so it ships full refresh with no explicit sort.
HOUSECALL_PRO_ENDPOINTS: dict[str, HousecallProEndpointConfig] = {
    "customers": HousecallProEndpointConfig(
        name="customers",
        path="/customers",
        response_key="customers",
        partition_key="created_at",
        incremental_fields=[],
    ),
    "jobs": HousecallProEndpointConfig(
        name="jobs",
        path="/jobs",
        response_key="jobs",
        partition_key="created_at",
        incremental_fields=[],
    ),
    "estimates": HousecallProEndpointConfig(
        name="estimates",
        path="/estimates",
        response_key="estimates",
        partition_key="created_at",
        incremental_fields=[],
    ),
    "invoices": HousecallProEndpointConfig(
        name="invoices",
        path="/invoices",
        response_key="invoices",
        partition_key="created_at",
        sort_field="created_at",
        incremental_param="created_at_min",
        supports_incremental=True,
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "employees": HousecallProEndpointConfig(
        name="employees",
        path="/employees",
        response_key="employees",
        incremental_fields=[],
    ),
    "leads": HousecallProEndpointConfig(
        name="leads",
        path="/leads",
        response_key="leads",
        partition_key="created_at",
        incremental_fields=[],
    ),
    "job_types": HousecallProEndpointConfig(
        name="job_types",
        path="/job_fields/job_types",
        response_key="job_types",
        incremental_fields=[],
    ),
    "pipeline_statuses": HousecallProEndpointConfig(
        name="pipeline_statuses",
        path="/pipeline/statuses",
        response_key="statuses",
        incremental_fields=[],
        resource_types=("lead", "job", "estimate"),
        # The docs do not say that status ids are unique across resource types.
        primary_keys=["resource_type", "id"],
    ),
    "job_appointments": HousecallProEndpointConfig(
        name="job_appointments",
        path="/jobs/{job_id}/appointments",
        response_key="appointments",
        incremental_fields=[],
        primary_keys=["job_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="jobs",
            resolve_param="job_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "job_id"},
            parent_params={"page_size": PAGE_SIZE},
            # A job deleted between the jobs listing and its child fetch must not fail the sync.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "job_line_items": HousecallProEndpointConfig(
        name="job_line_items",
        path="/jobs/{job_id}/line_items",
        response_key="data",
        incremental_fields=[],
        primary_keys=["job_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="jobs",
            resolve_param="job_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "job_id"},
            parent_params={"page_size": PAGE_SIZE},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

ENDPOINTS = tuple(HOUSECALL_PRO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in HOUSECALL_PRO_ENDPOINTS.items()
}
