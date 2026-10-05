from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# Several Deel endpoints cap `limit` below 100, so stay safely under every cap.
PAGE_SIZE = 50


# Mutable by choice, not oversight: instances flow into `build_dependent_resource`'s
# `endpoint_configs: Mapping[str, FanoutEndpointLike]`, and mypy treats a frozen dataclass's fields
# as read-only, which is incompatible with that Protocol's plain (read-write) attributes.
@dataclass(frozen=False)
class DeelEndpointConfig:
    name: str
    path: str
    # Deel mixes pagination styles per endpoint: limit/offset with `page` metadata on most
    # endpoints, keyset cursors on others, and no pagination at all on the per-parent children.
    pagination: Literal["offset", "cursor", "none"]
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field used for datetime partitioning.
    partition_key: Optional[str] = None
    # Where the next-page cursor sits in the body, and the query param that sends it back. Deel
    # varies both per endpoint.
    cursor_path: tuple[str, ...] = ("page", "cursor")
    cursor_param: str = "after_cursor"
    # Body path to an explicit "another page exists" flag, on the endpoints that publish one.
    has_more_path: Optional[tuple[str, ...]] = None
    # Query param carrying the page size; None for the endpoints that accept no size param.
    page_size_param: Optional[str] = "limit"
    page_size: int = PAGE_SIZE
    data_selector: str = "data"
    # Extra query params sent on every request to this endpoint.
    params: dict[str, Any] = field(default_factory=dict)
    fanout: Optional[DependentEndpointConfig] = None
    # Deel exposes no updated-since filter on the endpoints synced here, so both stay empty —
    # `FanoutEndpointLike` requires them.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None


# Core HR objects expose no updated-since filter and invoices change status
# after issuing, so every stream is an honest full refresh (matching Fivetran's
# Lite connector). Date-range incremental on invoices/timesheets is a possible
# follow-up once the filter behavior is verified against a live account, as is
# `updated_start_date` on time_offs.
DEEL_ENDPOINTS: dict[str, DeelEndpointConfig] = {
    "people": DeelEndpointConfig(
        name="people",
        path="/people",
        pagination="offset",
    ),
    "contracts": DeelEndpointConfig(
        name="contracts",
        path="/contracts",
        pagination="cursor",
        partition_key="created_at",
    ),
    "invoices": DeelEndpointConfig(
        name="invoices",
        path="/invoices",
        pagination="offset",
    ),
    "invoice_adjustments": DeelEndpointConfig(
        name="invoice_adjustments",
        path="/invoice-adjustments",
        pagination="offset",
    ),
    "timesheets": DeelEndpointConfig(
        name="timesheets",
        path="/timesheets",
        pagination="offset",
        partition_key="created_at",
    ),
    "payments": DeelEndpointConfig(
        name="payments",
        path="/payments",
        pagination="cursor",
        cursor_path=("data", "next_cursor"),
        cursor_param="cursor",
        has_more_path=("data", "has_more"),
        data_selector="data.rows",
        # /payments accepts no page-size param.
        page_size_param=None,
        partition_key="created_at",
    ),
    "payment_breakdowns": DeelEndpointConfig(
        name="payment_breakdowns",
        path="/payments/{payment_id}/breakdown",
        pagination="none",
        # Breakdown rows carry no id of their own: one row per contract line of a payment.
        primary_keys=["payment_id", "contract_id", "invoice_id"],
        page_size_param=None,
        fanout=DependentEndpointConfig(
            parent_name="payments",
            resolve_param="payment_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "payment_id"},
        ),
    ),
    "legal_entities": DeelEndpointConfig(
        name="legal_entities",
        path="/legal-entities",
        pagination="cursor",
        cursor_param="cursor",
        params={"sort_order": "ASC"},
    ),
    "cost_centers": DeelEndpointConfig(
        name="cost_centers",
        path="/legal-entities/{legal_entity_id}/cost-centers",
        pagination="none",
        # Deel does not document the cost centre id as unique outside its legal entity.
        primary_keys=["legal_entity_id", "id"],
        page_size_param=None,
        fanout=DependentEndpointConfig(
            parent_name="legal_entities",
            resolve_param="legal_entity_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "legal_entity_id"},
            parent_params={"limit": PAGE_SIZE, "sort_order": "ASC"},
        ),
    ),
    "time_offs": DeelEndpointConfig(
        name="time_offs",
        path="/time_offs",
        pagination="cursor",
        cursor_path=("next",),
        cursor_param="next",
        has_more_path=("has_next_page",),
        page_size_param="page_size",
        partition_key="created_at",
    ),
    "time_off_events": DeelEndpointConfig(
        name="time_off_events",
        path="/time_offs/time-off-events",
        pagination="none",
        # Deel does not document the event id as unique outside its worker profile.
        primary_keys=["hris_profile_id", "id"],
        page_size_param=None,
    ),
    "departments": DeelEndpointConfig(
        name="departments",
        path="/departments",
        pagination="none",
        page_size_param=None,
    ),
    "teams": DeelEndpointConfig(
        name="teams",
        path="/teams",
        pagination="none",
        page_size_param=None,
    ),
    "groups": DeelEndpointConfig(
        name="groups",
        path="/groups",
        pagination="cursor",
        cursor_param="cursor",
        params={"sort_order": "ASC"},
        partition_key="created_at",
    ),
    "onboarding_tracker": DeelEndpointConfig(
        name="onboarding_tracker",
        path="/onboarding/tracker",
        pagination="cursor",
        cursor_param="cursor",
        # One row per worker being onboarded; the tracker carries no id of its own.
        primary_keys=["unique_id"],
        params={"sort_order": "ASC"},
    ),
    "offboarding_tracker": DeelEndpointConfig(
        name="offboarding_tracker",
        path="/offboarding/tracker",
        pagination="cursor",
        cursor_param="cursor",
        primary_keys=["unique_id"],
        # Without `ignore_date_range` Deel returns only the last 45 days of terminations.
        params={"sort_order": "ASC", "ignore_date_range": "true"},
    ),
    "payroll_cycles": DeelEndpointConfig(
        name="payroll_cycles",
        path="/legal-entities/{legal_entity_id}/payroll-events",
        pagination="cursor",
        cursor_path=("next_cursor",),
        cursor_param="cursor",
        has_more_path=("has_more",),
        # Deel does not document the cycle id as unique outside its legal entity.
        primary_keys=["legal_entity_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="legal_entities",
            resolve_param="legal_entity_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "legal_entity_id"},
            parent_params={"limit": PAGE_SIZE, "sort_order": "ASC"},
            child_params={"limit": PAGE_SIZE},
        ),
    ),
    "payroll_reports": DeelEndpointConfig(
        name="payroll_reports",
        path="/gp/legal-entities/{legal_entity_id}/reports",
        pagination="none",
        # Global payroll events sit in their own id space; scope them to their legal entity.
        primary_keys=["legal_entity_id", "id"],
        page_size_param=None,
        fanout=DependentEndpointConfig(
            parent_name="legal_entities",
            resolve_param="legal_entity_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "legal_entity_id"},
            parent_params={"limit": PAGE_SIZE, "sort_order": "ASC"},
        ),
    ),
    "payroll_gross_to_net": DeelEndpointConfig(
        name="payroll_gross_to_net",
        path="/reports/payroll/cycles/{cycle_id}/gross-to-net",
        pagination="cursor",
        cursor_path=("next_cursor",),
        cursor_param="cursor",
        has_more_path=("has_more",),
        # One row per contract in a payroll cycle. The cycle is only unique within its legal
        # entity, so the entity leads the key here the same way it does on payroll_cycles.
        primary_keys=["legal_entity_id", "cycle_id", "contract_oid"],
    ),
    "countries": DeelEndpointConfig(
        name="countries",
        path="/lookups/countries",
        pagination="none",
        primary_keys=["code"],
        page_size_param=None,
    ),
    "currencies": DeelEndpointConfig(
        name="currencies",
        path="/lookups/currencies",
        pagination="none",
        primary_keys=["code"],
        page_size_param=None,
    ),
    "job_titles": DeelEndpointConfig(
        name="job_titles",
        path="/lookups/job-titles",
        pagination="cursor",
        # Job titles echo a cursor even past the last page, so the walk ends on the empty page
        # that cursor returns rather than on a missing cursor.
        cursor_param="after_cursor",
        # /lookups/job-titles accepts no page-size param.
        page_size_param=None,
    ),
    "seniorities": DeelEndpointConfig(
        name="seniorities",
        path="/lookups/seniorities",
        pagination="none",
        page_size_param=None,
    ),
}

# `/time_offs/time-off-events` takes its worker profile as a query param, which the shared fan-out
# helper cannot bind (it binds path params only), so it walks its parent by hand.
TIME_OFF_EVENTS_ENDPOINT = "time_off_events"
TIME_OFF_EVENTS_PARENT = "people"

# Gross-to-net is keyed by payroll cycle, and cycles are only listed per legal entity, so this
# endpoint is two hops from a top-level listing — one more than the shared fan-out helper binds.
GROSS_TO_NET_ENDPOINT = "payroll_gross_to_net"
GROSS_TO_NET_PARENT = "payroll_cycles"
GROSS_TO_NET_ROOT = "legal_entities"

ENDPOINTS = tuple(DEEL_ENDPOINTS.keys())
