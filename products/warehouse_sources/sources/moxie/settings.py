from dataclasses import field
from typing import Any, Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, frozen

# Moxie's Public API is served from a per-workspace pod host (e.g. `pod00.withmoxie.dev`), captured
# as the `base_url` credential field rather than hardcoded here. This is the path segment every pod
# appends after its host, per the endpoint-specific Help Center articles (List Clients, Search
# Contacts, etc). The overview "Public API Fundamentals" article shows an older `/clients/create`
# path shape with no `/action/` segment, but every endpoint-specific article agrees on `/action/...`,
# so that's what this source targets.
MOXIE_API_PATH_PREFIX = "/action"

# Moxie allows 100 Public API requests per 5 minutes per workspace. A fan-out table sends one
# request per parent, so it paces itself just under that limit.
FANOUT_REQUESTS_PER_SECOND = 90 / 300
# A 429 with no Retry-After holds the requests this long. The limit window is 5 minutes, so a
# short hold only earns the next 429.
FANOUT_RATE_LIMIT_HOLD_SECONDS = 60.0


@frozen
class MoxieEndpointConfig:
    name: str
    """Table name we expose to the user (snake_case)."""
    path: str
    """Path relative to `base_url`, including the `/action` prefix."""
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: Optional[str] = None
    """Stable creation-time field used for Delta partitioning; None leaves the table unpartitioned."""
    wrap_scalar_as: Optional[str] = None
    """Set when the endpoint returns a bare array of strings (e.g. template names) rather than
    objects, naming the single column each string is wrapped into."""
    params: dict[str, Any] = field(default_factory=dict)
    fanout: Optional[DependentEndpointConfig] = None
    # `build_dependent_resource` reads these three fields. No Moxie table is incremental, and the
    # page size of a fan-out child goes in its `params`.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    page_size: int = 100


def _fanout(parent_name: str, resolve_param: str) -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name=parent_name,
        resolve_param=resolve_param,
        resolve_field="id",
        # Child rows already carry their parent id.
        include_from_parent=[],
        # A parent deleted between the parent listing and its child fetch returns 404. Skip it.
        child_response_actions=[{"status_code": 404, "action": "ignore"}],
    )


# Moxie's Public API (https://help.withmoxie.com/en/collections/5482062-public-api-endpoints) exposes
# no pagination and no server-side timestamp filter on any list/search endpoint, so every table here
# is full refresh only. `clients` uses List Clients rather than Search Clients: Search Clients
# requires a `query` parameter, which can't express "give me everything", while List Clients takes no
# parameters at all. Contacts, Projects, and Payable Invoices only have a Search endpoint, but their
# `query` parameter is documented as optional, so omitting it returns the full collection.
#
# The client object's own documented response omits an `id` field entirely (Contacts, Projects, and
# Payable Invoices all reference a client by `clientId`, so one exists internally) — `name` is the
# best available key. Full refresh replaces the whole table each sync, so this doesn't risk a merge
# blow-up the way a non-unique key would on an incrementally-merged table.
MOXIE_ENDPOINTS: dict[str, MoxieEndpointConfig] = {
    "clients": MoxieEndpointConfig(name="clients", path=f"{MOXIE_API_PATH_PREFIX}/clients/list", primary_keys=["name"]),
    "contacts": MoxieEndpointConfig(name="contacts", path=f"{MOXIE_API_PATH_PREFIX}/contacts/search"),
    "projects": MoxieEndpointConfig(
        name="projects", path=f"{MOXIE_API_PATH_PREFIX}/projects/search", partition_key="dateCreated"
    ),
    "payable_invoices": MoxieEndpointConfig(
        name="payable_invoices",
        path=f"{MOXIE_API_PATH_PREFIX}/payableInvoices/search",
        partition_key="dateCreated",
    ),
    "email_templates": MoxieEndpointConfig(
        name="email_templates",
        path=f"{MOXIE_API_PATH_PREFIX}/emailTemplates/list",
        primary_keys=["name"],
        wrap_scalar_as="name",
    ),
    "invoice_templates": MoxieEndpointConfig(
        name="invoice_templates",
        path=f"{MOXIE_API_PATH_PREFIX}/invoiceTemplates/list",
        primary_keys=["name"],
        wrap_scalar_as="name",
    ),
    "vendor_names": MoxieEndpointConfig(
        name="vendor_names",
        path=f"{MOXIE_API_PATH_PREFIX}/vendors/list",
        primary_keys=["name"],
        wrap_scalar_as="name",
    ),
    "form_names": MoxieEndpointConfig(
        name="form_names",
        path=f"{MOXIE_API_PATH_PREFIX}/formNames/list",
        primary_keys=["name"],
        wrap_scalar_as="name",
    ),
    "pipeline_stages": MoxieEndpointConfig(name="pipeline_stages", path=f"{MOXIE_API_PATH_PREFIX}/pipelineStages/list"),
    "task_stages": MoxieEndpointConfig(name="task_stages", path=f"{MOXIE_API_PATH_PREFIX}/taskStages/list"),
    # List Tasks and List Tickets default to `archived=false`, so archived records are not synced.
    "tasks": MoxieEndpointConfig(name="tasks", path=f"{MOXIE_API_PATH_PREFIX}/tasks/list", partition_key="created"),
    "tickets": MoxieEndpointConfig(
        name="tickets", path=f"{MOXIE_API_PATH_PREFIX}/tickets/list", partition_key="created"
    ),
    "agreements": MoxieEndpointConfig(
        name="agreements", path=f"{MOXIE_API_PATH_PREFIX}/agreements/search", partition_key="dateCreated"
    ),
    # Rows are keyed by the nested `user.userId`, flattened onto the row root as `user_id` (see
    # `moxie.py`) since a nested field can't be declared as a primary key.
    "workspace_users": MoxieEndpointConfig(
        name="workspace_users", path=f"{MOXIE_API_PATH_PREFIX}/users/list", primary_keys=["user_id"]
    ),
    # Without `includeArchived` the search leaves out archived opportunities. Rows carry an
    # `archive` flag, so the table keeps them and a query can filter them out.
    "opportunities": MoxieEndpointConfig(
        name="opportunities",
        path=f"{MOXIE_API_PATH_PREFIX}/opportunities/search",
        partition_key="created",
        params={"includeArchived": "true"},
    ),
    # `moxie.py` splits the `timerStart` window when one call reaches the API's row cap.
    "time_entries": MoxieEndpointConfig(
        name="time_entries", path=f"{MOXIE_API_PATH_PREFIX}/timeWorked/list", partition_key="timestamp"
    ),
    # Without `commentType=ALL` the API returns only public replies and leaves out internal notes.
    "ticket_comments": MoxieEndpointConfig(
        name="ticket_comments",
        path=f"{MOXIE_API_PATH_PREFIX}/tickets/comments/list?ticketId={{ticketId}}",
        primary_keys=["ticketId", "id"],
        partition_key="created",
        params={"commentType": "ALL", "limit": 100},
        fanout=_fanout("tickets", "ticketId"),
    ),
    "project_notes": MoxieEndpointConfig(
        name="project_notes",
        path=f"{MOXIE_API_PATH_PREFIX}/projects/notes/search?projectId={{projectId}}",
        primary_keys=["projectId", "id"],
        partition_key="timestamp",
        fanout=_fanout("projects", "projectId"),
    ),
}

ENDPOINTS = tuple(MOXIE_ENDPOINTS.keys())
