from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.types import IncrementalField

# Nuntly caps every list endpoint at 30 rows per page (no larger tier is documented).
MAX_PAGE_SIZE = 30

# A parent deleted (or aged out by data retention) between the parent listing and its child fetch 404s.
_SKIP_MISSING_PARENT: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}]


@frozen
class NuntlyEndpointConfig:
    name: str
    path: str
    table_name: str
    primary_keys: list[str]
    # `createdAt` is stable across every endpoint below; none expose an `updated_at` equivalent.
    partition_key: str = "createdAt"
    page_size: int = MAX_PAGE_SIZE
    # Unpaginated endpoints return their whole collection in one `{"data": [...]}` body.
    paginated: bool = True
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    # Set for resources only listed per parent; the parent is re-listed each sync.
    fanout: DependentEndpointConfig | None = None
    # The fan-out checkpoint lists every finished parent and is rewritten after each one, so its
    # cost grows quadratically with the parent count. Turn it off where parents are unbounded.
    checkpoint_fanout: bool = True


ENDPOINTS: dict[str, NuntlyEndpointConfig] = {
    "Emails": NuntlyEndpointConfig(name="Emails", path="/emails", table_name="emails", primary_keys=["id"]),
    "Messages": NuntlyEndpointConfig(name="Messages", path="/messages", table_name="messages", primary_keys=["id"]),
    "Inboxes": NuntlyEndpointConfig(name="Inboxes", path="/inboxes", table_name="inboxes", primary_keys=["id"]),
    "Domains": NuntlyEndpointConfig(name="Domains", path="/domains", table_name="domains", primary_keys=["id"]),
    "Webhooks": NuntlyEndpointConfig(name="Webhooks", path="/webhooks", table_name="webhooks", primary_keys=["id"]),
    "Namespaces": NuntlyEndpointConfig(
        name="Namespaces", path="/namespaces", table_name="namespaces", primary_keys=["id"]
    ),
    "Contacts": NuntlyEndpointConfig(name="Contacts", path="/contacts", table_name="contacts", primary_keys=["id"]),
    "Threads": NuntlyEndpointConfig(
        name="Threads",
        path="/inboxes/{inboxId}/threads",
        table_name="threads",
        primary_keys=["inboxId", "id"],
        fanout=DependentEndpointConfig(
            parent_name="Inboxes",
            resolve_param="inboxId",
            resolve_field="id",
            # Thread rows already carry `inboxId`; nothing to copy down.
            include_from_parent=[],
            parent_params={"limit": MAX_PAGE_SIZE},
            child_params={"limit": MAX_PAGE_SIZE},
            child_response_actions=_SKIP_MISSING_PARENT,
        ),
    ),
    "EmailEvents": NuntlyEndpointConfig(
        name="EmailEvents",
        path="/emails/{emailId}/events",
        table_name="email_events",
        primary_keys=["emailId", "id"],
        paginated=False,
        # One parent per sent email, so a resumed run starts over rather than carry that list.
        checkpoint_fanout=False,
        fanout=DependentEndpointConfig(
            parent_name="Emails",
            resolve_param="emailId",
            resolve_field="id",
            # Event rows already carry `emailId`; nothing to copy down.
            include_from_parent=[],
            parent_params={"limit": MAX_PAGE_SIZE},
            child_response_actions=_SKIP_MISSING_PARENT,
        ),
    ),
}

# Nuntly documents no server-side timestamp filter on any list endpoint (no `since` /
# `updated_after` / date-range param), so every endpoint is full-refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
