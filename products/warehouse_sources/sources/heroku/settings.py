from collections.abc import Callable
from dataclasses import field
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

HEROKU_BASE_URL = "https://api.heroku.com"

# Heroku pages via the `Range` request header / `Next-Range` response header.
# Default page size is 200; the hard max is 1000.
DEFAULT_PAGE_SIZE = 1000

# Hard cap on pages walked per list (per parent for fan-out endpoints) so a runaway
# cursor can't scan unbounded history. 1000-row pages make this 100k rows per list.
MAX_PAGES_PER_LIST = 100

# Months of team usage requested per sync, current month included. Usage syncs as a full
# refresh, so the table holds this rolling window.
TEAM_USAGE_LOOKBACK_MONTHS = 12


@frozen
class HerokuEndpointConfig:
    name: str
    path: str  # contains a {parent_id} placeholder for fan-out endpoints
    # Endpoint whose rows' `id` fills `{parent_id}`; None for top-level lists.
    fan_out_parent: str | None = None
    # Parent rows to skip before fanning out, for children that only exist on some parents.
    parent_filter: Callable[[dict[str, Any]], bool] | None = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation timestamp used for datetime partitioning. All Heroku resources carry
    # `created_at`; never partition on `updated_at` (partitions would rewrite every sync).
    partition_key: str | None = "created_at"
    # Attribute used in the `Range` header for stable pagination. `id` is Heroku's default
    # sort attribute and is accepted on every list endpoint.
    range_attribute: str = "id"
    # False for endpoints that return one unpaginated array rather than a `Range`-cursored list.
    paginated: bool = True
    # Send `start`/`end` (YYYY-MM) covering the last TEAM_USAGE_LOOKBACK_MONTHS; usage endpoints
    # require `start`.
    month_window: bool = False
    should_sync_default: bool = True
    # Dotted paths of capability URLs nulled before rows are yielded. These URLs grant
    # access (source downloads, output streams, dyno attach) without Heroku auth, so they
    # must not land in the warehouse where any member with query access could read them.
    sensitive_fields: list[str] = field(default_factory=list)


# Heroku's Platform API v3 exposes no updated-since/created-since query filters, so every
# endpoint syncs as a full refresh. The `Range` header can filter some endpoints server-side
# (e.g. /apps advertises ranges on `updated_at`), but that behavior is per-endpoint and
# unverified against the live API, so we don't build incremental sync on it yet.
HEROKU_ENDPOINTS: dict[str, HerokuEndpointConfig] = {
    "apps": HerokuEndpointConfig(
        name="apps",
        path="/apps",
    ),
    "addons": HerokuEndpointConfig(
        name="addons",
        path="/addons",
    ),
    "addon_attachments": HerokuEndpointConfig(
        name="addon_attachments",
        path="/addon-attachments",
        sensitive_fields=["log_input_url"],
    ),
    "builds": HerokuEndpointConfig(
        name="builds",
        path="/apps/{parent_id}/builds",
        fan_out_parent="apps",
        sensitive_fields=["output_stream_url", "source_blob.url"],
    ),
    "collaborators": HerokuEndpointConfig(
        name="collaborators",
        path="/apps/{parent_id}/collaborators",
        fan_out_parent="apps",
    ),
    "domains": HerokuEndpointConfig(
        name="domains",
        path="/apps/{parent_id}/domains",
        fan_out_parent="apps",
    ),
    # Dynos are a point-in-time snapshot of running processes; the list is small and churns
    # constantly, so partitioning adds nothing.
    "dynos": HerokuEndpointConfig(
        name="dynos",
        path="/apps/{parent_id}/dynos",
        fan_out_parent="apps",
        partition_key=None,
        sensitive_fields=["attach_url"],
    ),
    "formation": HerokuEndpointConfig(
        name="formation",
        path="/apps/{parent_id}/formation",
        fan_out_parent="apps",
        partition_key=None,
    ),
    "invoices": HerokuEndpointConfig(
        name="invoices",
        path="/account/invoices",
    ),
    "pipelines": HerokuEndpointConfig(
        name="pipelines",
        path="/pipelines",
    ),
    "pipeline_couplings": HerokuEndpointConfig(
        name="pipeline_couplings",
        path="/pipeline-couplings",
    ),
    "releases": HerokuEndpointConfig(
        name="releases",
        path="/apps/{parent_id}/releases",
        fan_out_parent="apps",
        sensitive_fields=["output_stream_url"],
    ),
    "teams": HerokuEndpointConfig(
        name="teams",
        path="/teams",
    ),
    # Usage only exists for teams that belong to a Heroku Enterprise account; other teams are
    # skipped. One row per team per month, and `id` is the team id, so the key is composite.
    "team_monthly_usage": HerokuEndpointConfig(
        name="team_monthly_usage",
        path="/teams/{parent_id}/usage/monthly",
        fan_out_parent="teams",
        parent_filter=lambda team: bool(team.get("enterprise_account")),
        primary_keys=["id", "month"],
        partition_key=None,
        paginated=False,
        month_window=True,
        # Enterprise-only, so most accounts would sync an empty table; opt in explicitly.
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(HEROKU_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in HEROKU_ENDPOINTS}
