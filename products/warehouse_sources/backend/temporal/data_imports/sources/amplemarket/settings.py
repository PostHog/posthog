from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.amplemarket.com"


@frozen
class AmplemarketEndpointConfig:
    name: str
    path: str
    # The key the row objects are nested under in the response body (e.g. {"sequences": [...]}).
    data_key: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
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

# A parent deleted between the parent listing and the child fetch answers 404 (or 410 for a
# lead list), which should drop that parent rather than fail the sync.
_DELETED_PARENT_IGNORE: list[ResponseAction] = [
    {"status_code": 404, "action": "ignore"},
    {"status_code": 410, "action": "ignore"},
]

# /contacts has no unfiltered listing (it requires a name, account_id, or ids[] filter), so
# contacts fan out over the accounts list. Contacts not linked to an account are not reachable.
_CONTACTS_FANOUT = DependentEndpointConfig(
    parent_name="accounts",
    resolve_param="account_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "account_id"},
    child_response_actions=_DELETED_PARENT_IGNORE,
)

# The lead list listing carries only list summaries; the entries come from each list's detail
# endpoint, paged under `leads`.
_LEAD_LIST_ENTRIES_FANOUT = DependentEndpointConfig(
    parent_name="lead_lists",
    resolve_param="lead_list_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "lead_list_id"},
    child_response_actions=_DELETED_PARENT_IGNORE,
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
# collections: people/company search and enrichment, email validation, job openings (a search
# over Amplemarket's company data by domain, not records in the customer's account), and the
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
    # Keyed with the account id, because the API does not document that a contact belongs to
    # exactly one account.
    "contacts": AmplemarketEndpointConfig(
        name="contacts",
        path="/contacts?account_id={account_id}",
        data_key="contacts",
        primary_keys=["account_id", "id"],
        partition_key="created_at",
        fanout=_CONTACTS_FANOUT,
    ),
    "excluded_domains": AmplemarketEndpointConfig(
        name="excluded_domains",
        path="/excluded-domains",
        data_key="excluded_domains",
        primary_keys=["domain"],
        partition_key="date_added",
    ),
    "excluded_emails": AmplemarketEndpointConfig(
        name="excluded_emails",
        path="/excluded-emails",
        data_key="excluded_emails",
        primary_keys=["email"],
        partition_key="date_added",
    ),
    "lead_lists": AmplemarketEndpointConfig(
        name="lead_lists",
        path="/lead-lists",
        data_key="lead_lists",
    ),
    # Entries are keyed with their list id, because the same person can sit on several lists and
    # entry ids are not documented as unique across lists. Entries carry no creation time.
    "lead_list_entries": AmplemarketEndpointConfig(
        name="lead_list_entries",
        path="/lead-lists/{lead_list_id}",
        data_key="leads",
        primary_keys=["lead_list_id", "id"],
        fanout=_LEAD_LIST_ENTRIES_FANOUT,
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
