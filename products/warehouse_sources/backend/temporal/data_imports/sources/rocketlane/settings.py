from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)

# The list endpoints cap `pageSize` at 100 (values above the cap fall back to 100), so 100 minimises
# round trips.
PAGE_SIZE = 100


@dataclass  # nosemgrep: prefer-frozen-dataclasses -- pre-existing; new field shifts the backlog finding into diff
class RocketlaneEndpointConfig:
    name: str
    path: str
    # Each Rocketlane object type exposes its own system-generated identifier field
    # (projectId, taskId, ...) rather than a shared `id`, so the primary key is per-endpoint.
    primary_keys: list[str]
    # A stable (never-rewritten) creation timestamp to partition by, where the object exposes one.
    # Rocketlane timestamps are epoch milliseconds; only set this where the field is genuinely
    # immutable — never `updatedAt`, which changes on every edit.
    partition_key: Optional[str] = None
    # Set for endpoints that take a parent id (a `projectId` filter, an invoice id in the path):
    # they are fetched once per row of the parent endpoint.
    fanout: Optional[DependentEndpointConfig] = None
    page_size: int = PAGE_SIZE
    incremental_fields: list[Any] = field(default_factory=list)
    default_incremental_field: Optional[str] = None


# All endpoints are full-refresh only: Rocketlane's list endpoints expose per-field filters but no
# single documented `updated_after` cursor, so there is no genuine incremental cursor to advance.
ROCKETLANE_ENDPOINTS: dict[str, RocketlaneEndpointConfig] = {
    "projects": RocketlaneEndpointConfig(
        name="projects", path="/projects", primary_keys=["projectId"], partition_key="createdAt"
    ),
    "tasks": RocketlaneEndpointConfig(name="tasks", path="/tasks", primary_keys=["taskId"], partition_key="createdAt"),
    "time_entries": RocketlaneEndpointConfig(
        name="time_entries", path="/time-entries", primary_keys=["timeEntryId"], partition_key="createdAt"
    ),
    "users": RocketlaneEndpointConfig(name="users", path="/users", primary_keys=["userId"], partition_key="createdAt"),
    "fields": RocketlaneEndpointConfig(
        name="fields", path="/fields", primary_keys=["fieldId"], partition_key="createdAt"
    ),
    "invoices": RocketlaneEndpointConfig(
        name="invoices", path="/invoices", primary_keys=["invoiceId"], partition_key="createdAt"
    ),
    # Line items carry no timestamps and the API does not document their ids as globally unique, so
    # the parent invoice id is part of the key.
    "invoice_line_items": RocketlaneEndpointConfig(
        name="invoice_line_items",
        path="/invoices/{invoiceId}/lines",
        primary_keys=["invoiceId", "invoiceLineItemId"],
        fanout=DependentEndpointConfig(
            parent_name="invoices",
            resolve_param="invoiceId",
            resolve_field="invoiceId",
            include_from_parent=["invoiceId"],
            parent_field_renames={"invoiceId": "invoiceId"},
            # An invoice deleted between the parent listing and this fetch must not fail the fan-out.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "time_entry_categories": RocketlaneEndpointConfig(
        name="time_entry_categories", path="/time-entries/categories", primary_keys=["categoryId"]
    ),
    # `/phases` requires a `projectId` filter. Each phase row already carries its `project`, and
    # `phaseId` is documented as globally unique.
    "phases": RocketlaneEndpointConfig(
        name="phases",
        path="/phases?projectId={projectId}",
        primary_keys=["phaseId"],
        partition_key="createdAt",
        fanout=DependentEndpointConfig(
            parent_name="projects",
            resolve_param="projectId",
            resolve_field="projectId",
            include_from_parent=[],
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

ENDPOINTS = tuple(ROCKETLANE_ENDPOINTS.keys())

# Full refresh only — see the note above. Kept for parity with the incremental-capable sources.
INCREMENTAL_FIELDS: dict[str, list] = {}
