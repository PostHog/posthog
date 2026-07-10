from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField

# Netlify exposes no server-side timestamp filter on any list endpoint (no `since` / `updated_after`
# / `created_gte` param filters the results — they're documented but silently ignored, or absent),
# so every table is full refresh. There is no reliable server-side cursor to sync incrementally on.
# `INCREMENTAL_FIELDS` is therefore empty for all endpoints; see the module docstring in netlify.py.


@dataclass
class NetlifyEndpointConfig:
    name: str
    # Path template appended to the API base. Fan-out children carry a placeholder filled from the
    # parent: {site_id} for site-scoped tables, {account_slug} for account-scoped tables.
    path: str
    # Primary key columns for upsert dedup. Fan-out children key on the parent identifier too so the
    # key stays unique table-wide (a build/submission id is only guaranteed unique within its site).
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field to partition by. Never a mutable field (`updated_at`) — partitions
    # must not rewrite on every sync. None for tables the API returns without a timestamp (members).
    partition_key: Optional[str] = None
    # Send `per_page` on the request when set. None for endpoints that document no page/per_page
    # params (forms, dns_zones, accounts, members return a single unpaginated list).
    page_size: Optional[int] = 100
    # Order rows actually arrive in, so SourceResponse.sort_mode reflects reality. Netlify returns
    # deploys/builds/submissions newest-first; the small full-refresh lists are creation-ordered.
    # All tables are full refresh, so this doesn't drive an incremental watermark — it just stays honest.
    sort_mode: Literal["asc", "desc"] = "asc"
    should_sync_default: bool = True
    # Fan-out: the parent endpoint whose rows seed this child's path.
    fan_out_parent: Optional[str] = None
    # Path placeholder filled from the parent (e.g. "site_id") and the parent field read for it.
    fan_out_path_param: Optional[str] = None
    fan_out_parent_field: str = "id"
    # Parent fields copied onto each child row, mapped parent_field -> child_column. Gives fan-out
    # children the parent context their own API response omits (a build/submission carries no site_id).
    fan_out_include_parent_fields: Optional[dict[str, str]] = None
    # Hard cap on pages fetched per parent in a fan-out, bounding a runaway paginator. Logged on hit.
    max_pages_per_parent: int = 100


NETLIFY_ENDPOINTS: dict[str, NetlifyEndpointConfig] = {
    "sites": NetlifyEndpointConfig(
        name="sites",
        path="/sites",
        partition_key="created_at",
    ),
    "deploys": NetlifyEndpointConfig(
        name="deploys",
        path="/sites/{site_id}/deploys",
        # Deploy ids are globally unique, but the composite key keeps us safe if that ever changes
        # and matches how the other site-scoped children key. The deploy already carries site_id;
        # injecting the parent's id under the same column is idempotent.
        primary_keys=["site_id", "id"],
        partition_key="created_at",
        sort_mode="desc",  # newest-first
        fan_out_parent="sites",
        fan_out_path_param="site_id",
        fan_out_include_parent_fields={"id": "site_id"},
    ),
    "builds": NetlifyEndpointConfig(
        name="builds",
        path="/sites/{site_id}/builds",
        # A build row carries no site_id of its own, so inject the parent site id and key on it.
        primary_keys=["site_id", "id"],
        partition_key="created_at",
        sort_mode="desc",  # newest-first
        fan_out_parent="sites",
        fan_out_path_param="site_id",
        fan_out_include_parent_fields={"id": "site_id"},
    ),
    "forms": NetlifyEndpointConfig(
        name="forms",
        path="/sites/{site_id}/forms",
        primary_keys=["site_id", "id"],
        partition_key="created_at",
        page_size=None,  # no page/per_page params; a site has few forms
        fan_out_parent="sites",
        fan_out_path_param="site_id",
        fan_out_include_parent_fields={"id": "site_id"},
    ),
    "submissions": NetlifyEndpointConfig(
        name="submissions",
        path="/sites/{site_id}/submissions",
        # Submission rows carry no site_id, so inject the parent site id and key on it.
        primary_keys=["site_id", "id"],
        partition_key="created_at",
        sort_mode="desc",  # newest-first
        fan_out_parent="sites",
        fan_out_path_param="site_id",
        fan_out_include_parent_fields={"id": "site_id"},
    ),
    "dns_zones": NetlifyEndpointConfig(
        name="dns_zones",
        path="/dns_zones",
        partition_key="created_at",
        page_size=None,
    ),
    "accounts": NetlifyEndpointConfig(
        name="accounts",
        path="/accounts",
        partition_key="created_at",
        page_size=None,
    ),
    "members": NetlifyEndpointConfig(
        name="members",
        path="/{account_slug}/members",
        # A member row is a plain user with an id that can recur across accounts, so key on the
        # account too; the account_slug has no member timestamp so this table isn't partitioned.
        primary_keys=["account_slug", "id"],
        page_size=None,
        fan_out_parent="accounts",
        fan_out_path_param="account_slug",
        fan_out_parent_field="slug",
        fan_out_include_parent_fields={"slug": "account_slug"},
    ),
}

ENDPOINTS = tuple(NETLIFY_ENDPOINTS.keys())

# Every endpoint is full refresh: Netlify has no server-side timestamp filter to sync incrementally on.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in NETLIFY_ENDPOINTS}
