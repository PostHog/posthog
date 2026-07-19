from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField

# How an endpoint's request URLs are derived:
#   "none"          -> a single top-level list endpoint (no parent fan-out)
#   "project"       -> one request per project the token can see
#   "organization"  -> one request per organization the token can see
#   "invoice"       -> one request per (organization, invoice) pair (two-level fan-out)
FanOut = Literal["none", "project", "organization", "invoice"]


@dataclass
class AivenEndpointConfig:
    name: str
    fan_out: FanOut
    # Relative path appended to the API base. Fan-out endpoints carry ``{project}``,
    # ``{organization_id}`` and/or ``{invoice_number}`` placeholders filled in per parent.
    path_template: str
    # Response wrapper key: Aiven list endpoints return ``{"<data_key>": [...]}``.
    data_key: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field used for datetime partitioning. Never an ``update_time``-style
    # field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    should_sync_default: bool = True


AIVEN_ENDPOINTS: dict[str, AivenEndpointConfig] = {
    # Top-level inventory.
    "projects": AivenEndpointConfig(
        name="projects",
        fan_out="none",
        path_template="/project",
        data_key="projects",
        primary_keys=["project_name"],
    ),
    "organizations": AivenEndpointConfig(
        name="organizations",
        fan_out="none",
        path_template="/organizations",
        data_key="organizations",
        primary_keys=["organization_id"],
        partition_key="create_time",
    ),
    # Fan out one request per project.
    "services": AivenEndpointConfig(
        name="services",
        fan_out="project",
        path_template="/project/{project}/service",
        data_key="services",
        # `service_name` is unique within a project but not across projects, so the injected
        # parent `project_name` is part of the key to keep it unique table-wide.
        primary_keys=["project_name", "service_name"],
        partition_key="create_time",
    ),
    # Fan out one request per organization.
    "billing_groups": AivenEndpointConfig(
        name="billing_groups",
        fan_out="organization",
        path_template="/organization/{organization_id}/billing-groups",
        data_key="billing_groups",
        primary_keys=["billing_group_id"],
        partition_key="create_time",
    ),
    "invoices": AivenEndpointConfig(
        name="invoices",
        fan_out="organization",
        path_template="/organization/{organization_id}/invoices",
        data_key="invoices",
        # `invoice_number` is only unique within an organization, so the injected
        # `organization_id` keeps the row unique table-wide.
        primary_keys=["organization_id", "invoice_number"],
        partition_key="create_time",
    ),
    "organization_users": AivenEndpointConfig(
        name="organization_users",
        fan_out="organization",
        path_template="/organization/{organization_id}/user",
        data_key="users",
        # A user can belong to more than one organization, so the injected `organization_id`
        # keeps the row unique across organizations.
        primary_keys=["organization_id", "user_id"],
        partition_key="join_time",
    ),
    "user_groups": AivenEndpointConfig(
        name="user_groups",
        fan_out="organization",
        path_template="/organization/{organization_id}/user-groups",
        data_key="user_groups",
        primary_keys=["organization_id", "user_group_id"],
        partition_key="create_time",
    ),
    # Two-level fan-out: per organization, per invoice. Aiven markets these per-line cost rows
    # as the canonical way to export billing into a warehouse/BI tool.
    "invoice_lines": AivenEndpointConfig(
        name="invoice_lines",
        fan_out="invoice",
        path_template="/organization/{organization_id}/invoice/{invoice_number}/lines",
        data_key="lines",
        # Invoice lines carry no server-assigned id. This composite is best-effort unique and the
        # table is full-refresh (replace), so a collision cannot accumulate duplicates across syncs.
        # `organization_id` scopes the key so identical invoice numbers across organizations don't collide.
        primary_keys=["organization_id", "invoice_number", "service_id", "line_type", "begin_time", "end_time"],
        partition_key="begin_time",
    ),
    # Global Aiven cloud/region catalogue. Not account-specific, so off by default.
    "clouds": AivenEndpointConfig(
        name="clouds",
        fan_out="none",
        path_template="/clouds",
        data_key="clouds",
        primary_keys=["cloud_name"],
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(AIVEN_ENDPOINTS.keys())

# Aiven's list endpoints expose no server-side timestamp filter (no `since`/`updated_after` query
# params on any of them), so every table ships full-refresh only. Declaring incremental support
# without a real server filter would make each "incremental" run cost the same as a full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
