from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# noCRM caps `/leads` at a default of 100 per page; request the max to minimise round-trips against
# the low (~2000 req/day) account quota.
PAGE_SIZE = 100


@dataclass(frozen=True)
class NoCRMEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    # True only when noCRM exposes a server-side change filter for this list endpoint. Today that's
    # just `/leads` via `updated_after`; every other endpoint is a small config/metadata list with no
    # timestamp filter, so it ships full refresh.
    supports_incremental: bool = False
    # Query param used for the server-side "changed since" filter (leads: `updated_after`).
    incremental_param: Optional[str] = None
    # `order` value that sorts the list ascending by the incremental field, so pages arrive in the
    # order the pipeline's `asc` watermark expects. Only set on incremental endpoints.
    incremental_sort_order: Optional[str] = None
    # `order` value for a stable ascending sort on full-refresh / non-incremental runs, guarding against
    # page-boundary skips if rows are inserted mid-sync. `None` means don't send an `order` param at all
    # (most metadata endpoints don't document one, so we avoid sending params they might reject).
    default_sort_order: Optional[str] = None
    # Stable creation timestamp used for datetime partitioning. None for small metadata endpoints with
    # no creation timestamp / not worth partitioning.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    # Set for endpoints noCRM only exposes per parent row (per lead / per user).
    fanout: Optional[DependentEndpointConfig] = None
    # False for child endpoints that return their whole collection in one response, with no
    # documented limit/offset params.
    paginated: bool = True
    default_incremental_field: Optional[str] = None
    page_size: int = PAGE_SIZE


def _updated_at_incremental_fields() -> list[IncrementalField]:
    # noCRM's `updated_after` filters leads by their last-update time, so `updated_at` is the only
    # meaningful incremental cursor. `created_at` is used for partitioning, not incremental sync.
    return [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


# Lead sub-resources are only listable per lead, so these fan out over `/leads` (one request per lead).
LEAD_FANOUT = DependentEndpointConfig(
    parent_name="leads",
    resolve_param="lead_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "lead_id"},
    # `/leads` hides unassigned leads unless asked, which would drop their histories and comments.
    parent_params={"order": "id", "direction": "asc", "include_unassigned": "true"},
    # A lead deleted between the parent listing and its child fetch 404s; skip it.
    child_response_actions=[{"status_code": 404, "action": "ignore"}],
)

# `/follow_ups` requires a `lead_id` or `user_id`. There are far fewer users than leads, so fan out
# over users. The default status set is undocumented, so ask for every status explicitly.
USER_FANOUT = DependentEndpointConfig(
    parent_name="users",
    resolve_param="user_id",
    resolve_field="id",
    include_from_parent=[],
    child_params={"status": "todo,standby,done"},
    child_response_actions=[{"status_code": 404, "action": "ignore"}],
)

NOCRM_ENDPOINTS: dict[str, NoCRMEndpointConfig] = {
    "leads": NoCRMEndpointConfig(
        name="leads",
        path="/leads",
        supports_incremental=True,
        incremental_param="updated_after",
        incremental_sort_order="last_update",
        default_sort_order="id",
        partition_key="created_at",
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "activities": NoCRMEndpointConfig(
        name="activities",
        path="/activities",
        incremental_fields=[],
    ),
    "users": NoCRMEndpointConfig(
        name="users",
        path="/users",
        incremental_fields=[],
    ),
    "teams": NoCRMEndpointConfig(
        name="teams",
        path="/teams",
        incremental_fields=[],
    ),
    "steps": NoCRMEndpointConfig(
        name="steps",
        path="/steps",
        incremental_fields=[],
    ),
    "pipelines": NoCRMEndpointConfig(
        name="pipelines",
        path="/pipelines",
        incremental_fields=[],
    ),
    "client_folders": NoCRMEndpointConfig(
        name="client_folders",
        path="/clients",
        incremental_fields=[],
    ),
    "categories": NoCRMEndpointConfig(
        name="categories",
        path="/categories",
        incremental_fields=[],
    ),
    "tags": NoCRMEndpointConfig(
        name="tags",
        path="/predefined_tags",
        incremental_fields=[],
    ),
    "fields": NoCRMEndpointConfig(
        name="fields",
        path="/fields",
        incremental_fields=[],
    ),
    # Per-lead fan-outs cost one request per lead against the daily quota, so they are opt-in.
    "lead_action_histories": NoCRMEndpointConfig(
        name="lead_action_histories",
        path="/leads/{lead_id}/action_histories",
        incremental_fields=[],
        partition_key="created_at",
        primary_keys=["lead_id", "id"],
        should_sync_default=False,
        fanout=LEAD_FANOUT,
    ),
    "lead_comments": NoCRMEndpointConfig(
        name="lead_comments",
        path="/leads/{lead_id}/comments",
        incremental_fields=[],
        partition_key="created_at",
        primary_keys=["lead_id", "id"],
        should_sync_default=False,
        fanout=LEAD_FANOUT,
        paginated=False,
    ),
    "follow_ups": NoCRMEndpointConfig(
        name="follow_ups",
        # The framework only binds resolve params in the path, so `user_id` rides in the query string here.
        path="/follow_ups?user_id={user_id}",
        incremental_fields=[],
        partition_key="created_at",
        fanout=USER_FANOUT,
        paginated=False,
    ),
}

ENDPOINTS = tuple(NOCRM_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in NOCRM_ENDPOINTS.items()
}
