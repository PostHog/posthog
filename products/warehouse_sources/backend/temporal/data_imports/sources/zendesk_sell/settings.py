from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ZendeskSellEndpointConfig:
    name: str
    # Path under the v2 base URL, e.g. "/v2/contacts".
    path: str
    # Every Core API resource exposes a globally-unique integer `id`, so a single-column key is safe.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation timestamp to partition by. Set only for the high-volume transactional resources;
    # the small config/lookup tables (pipelines, stages, tags, sources, reasons, outcomes) are left
    # unpartitioned because partitioning a handful of rows buys nothing. Never `updated_at` — partitions
    # must not move when a record is edited.
    partition_key: Optional[str] = None
    # Whether the table is selected for sync by default in the connection wizard.
    should_sync_default: bool = True


# Core API collection endpoints (https://api.getbase.com/v2/). Each returns the standard
# `{"items": [{"data": {...}}], "meta": {"links": {"next_page": ...}}}` envelope and is paginated by
# 1-based `page` + `per_page` (max 100). All are full-refresh: the Core API exposes `sort_by` but no
# server-side `updated_after`/`since` timestamp filter, so there is no cheap way to fetch only changed
# rows (see the module docstring in zendesk_sell.py).
ZENDESK_SELL_ENDPOINTS: dict[str, ZendeskSellEndpointConfig] = {
    "contacts": ZendeskSellEndpointConfig(name="contacts", path="/v2/contacts", partition_key="created_at"),
    "deals": ZendeskSellEndpointConfig(name="deals", path="/v2/deals", partition_key="created_at"),
    "leads": ZendeskSellEndpointConfig(name="leads", path="/v2/leads", partition_key="created_at"),
    "tasks": ZendeskSellEndpointConfig(name="tasks", path="/v2/tasks", partition_key="created_at"),
    "notes": ZendeskSellEndpointConfig(name="notes", path="/v2/notes", partition_key="created_at"),
    "calls": ZendeskSellEndpointConfig(name="calls", path="/v2/calls", partition_key="created_at"),
    "text_messages": ZendeskSellEndpointConfig(
        name="text_messages", path="/v2/text_messages", partition_key="created_at"
    ),
    "visits": ZendeskSellEndpointConfig(name="visits", path="/v2/visits", partition_key="created_at"),
    "orders": ZendeskSellEndpointConfig(name="orders", path="/v2/orders", partition_key="created_at"),
    "products": ZendeskSellEndpointConfig(name="products", path="/v2/products", partition_key="created_at"),
    "collaborations": ZendeskSellEndpointConfig(
        name="collaborations", path="/v2/collaborations", partition_key="created_at"
    ),
    "users": ZendeskSellEndpointConfig(name="users", path="/v2/users", partition_key="created_at"),
    # Small config / lookup resources — full refresh, no partitioning.
    "pipelines": ZendeskSellEndpointConfig(name="pipelines", path="/v2/pipelines"),
    "stages": ZendeskSellEndpointConfig(name="stages", path="/v2/stages"),
    "tags": ZendeskSellEndpointConfig(name="tags", path="/v2/tags"),
    "deal_sources": ZendeskSellEndpointConfig(name="deal_sources", path="/v2/deal_sources"),
    "lead_sources": ZendeskSellEndpointConfig(name="lead_sources", path="/v2/lead_sources"),
    "loss_reasons": ZendeskSellEndpointConfig(name="loss_reasons", path="/v2/loss_reasons"),
    "deal_unqualified_reasons": ZendeskSellEndpointConfig(
        name="deal_unqualified_reasons", path="/v2/deal_unqualified_reasons"
    ),
    "lead_unqualified_reasons": ZendeskSellEndpointConfig(
        name="lead_unqualified_reasons", path="/v2/lead_unqualified_reasons"
    ),
    "call_outcomes": ZendeskSellEndpointConfig(name="call_outcomes", path="/v2/call_outcomes"),
    "visit_outcomes": ZendeskSellEndpointConfig(name="visit_outcomes", path="/v2/visit_outcomes"),
}

ENDPOINTS = tuple(ZENDESK_SELL_ENDPOINTS.keys())
