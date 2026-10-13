from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.amplemarket.com"


@frozen
class AmplemarketEndpointConfig:
    name: str
    path: str
    # The key the row objects are nested under in the response body (e.g. {"sequences": [...]}).
    data_key: str
    primary_key: str = "id"
    # Stable creation-time field used for datetime partitioning. Never an updated_at-style
    # field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    sort_mode: SortMode = "asc"
    fanout: Optional[DependentEndpointConfig] = None
    # The remaining fields exist to satisfy the shared FanoutEndpointLike protocol; Amplemarket
    # page sizes come from the server defaults (see the module comment below), and no endpoint
    # is incremental yet.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    page_size: int = 100


# /tasks requires a user_id filter, so tasks fan out over the users list. Task ids are UUIDs,
# unique across users, so the child keeps its own id as the primary key.
_TASKS_FANOUT = DependentEndpointConfig(
    parent_name="users",
    resolve_param="user_id",
    resolve_field="id",
    include_from_parent=[],
)


# Pagination is cursor-based via `_links.next.href` (HAL-style relative URLs). Requests omit
# `page[size]` and follow the server defaults: the documented maximum varies per endpoint and
# is undocumented for most, so sending a larger size risks a 400 on some endpoints.
#
# Every endpoint is full refresh. `/calls` documents `start_date_from`/`start_date_to` filters
# (and returns newest first), but the filter is unverified against the live API and the
# newest-first order would need descending-watermark handling, so incremental sync is left off
# until the filter is proven to work.
#
# Deliberately not synced, because they are actions or per-query lookups rather than record
# collections: people/company search and enrichment, email validation, contacts (requires a
# name/account_id/ids filter), job openings (a prospecting search surface), and the
# credit-consuming endpoints.
AMPLEMARKET_ENDPOINTS: dict[str, AmplemarketEndpointConfig] = {
    "accounts": AmplemarketEndpointConfig(
        name="accounts",
        path="/accounts",
        data_key="accounts",
    ),
    "calls": AmplemarketEndpointConfig(
        name="calls",
        path="/calls",
        data_key="calls",
        partition_key="start_date",
        # /calls documents that it lists calls newest first.
        sort_mode="desc",
    ),
    "call_dispositions": AmplemarketEndpointConfig(
        name="call_dispositions",
        path="/calls/dispositions",
        data_key="dispositions",
    ),
    "excluded_domains": AmplemarketEndpointConfig(
        name="excluded_domains",
        path="/excluded-domains",
        data_key="excluded_domains",
        primary_key="domain",
        partition_key="date_added",
    ),
    "excluded_emails": AmplemarketEndpointConfig(
        name="excluded_emails",
        path="/excluded-emails",
        data_key="excluded_emails",
        primary_key="email",
        partition_key="date_added",
    ),
    "lead_lists": AmplemarketEndpointConfig(
        name="lead_lists",
        path="/lead-lists",
        data_key="lead_lists",
    ),
    "mailboxes": AmplemarketEndpointConfig(
        name="mailboxes",
        path="/mailboxes",
        data_key="mailboxes",
        partition_key="created_at",
    ),
    "sequences": AmplemarketEndpointConfig(
        name="sequences",
        path="/sequences",
        data_key="sequences",
        partition_key="created_at",
    ),
    # `{user_id}` is bound per parent user row by the fan-out; tasks carry no stable
    # creation-time field (due_on can be rescheduled), so no partitioning.
    "tasks": AmplemarketEndpointConfig(
        name="tasks",
        path="/tasks?user_id={user_id}",
        data_key="tasks",
        fanout=_TASKS_FANOUT,
    ),
    "users": AmplemarketEndpointConfig(
        name="users",
        path="/users",
        data_key="users",
    ),
}

ENDPOINTS = tuple(AMPLEMARKET_ENDPOINTS.keys())

# No endpoint has a verified server-side timestamp filter, so nothing advertises incremental
# sync (see the catalog comment above).
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
