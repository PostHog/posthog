from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

# Moxie's Public API is served from a per-workspace pod host (e.g. `pod00.withmoxie.dev`), captured
# as the `base_url` credential field rather than hardcoded here. This is the path segment every pod
# appends after its host, per the endpoint-specific Help Center articles (List Clients, Search
# Contacts, etc). The overview "Public API Fundamentals" article shows an older `/clients/create`
# path shape with no `/action/` segment, but every endpoint-specific article agrees on `/action/...`,
# so that's what this source targets.
MOXIE_API_PATH_PREFIX = "/action"


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
    # Rows are keyed by the nested `user.userId`, flattened onto the row root as `user_id` (see
    # `moxie.py`) since a nested field can't be declared as a primary key.
    "workspace_users": MoxieEndpointConfig(
        name="workspace_users", path=f"{MOXIE_API_PATH_PREFIX}/users/list", primary_keys=["user_id"]
    ),
}

ENDPOINTS = tuple(MOXIE_ENDPOINTS.keys())
