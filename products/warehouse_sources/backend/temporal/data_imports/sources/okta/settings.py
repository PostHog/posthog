from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass(frozen=True)
class OktaEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Field used to build the server-side incremental filter. Okta exposes `lastUpdated`
    # on most resources and `published` on the System Log.
    default_incremental_field: Optional[str] = None
    # How the incremental filter is sent to Okta:
    #   "filter"  -> ?filter=lastUpdated gt "<ts>"   (Users, Groups)
    #   "since"   -> ?since=<ts>                       (System Log)
    incremental_param: Optional[Literal["filter", "since"]] = None
    # Stable, immutable field to partition by. Never use lastUpdated (it mutates).
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    page_size: int = 200
    # False for list endpoints that return the whole collection in one response and take no `limit`.
    paginated: bool = True
    # Set for per-parent child endpoints (e.g. a group's members), which Okta only exposes nested
    # under the parent resource.
    fanout: Optional[DependentEndpointConfig] = None
    # False skips fan-out checkpoints: the shared fan-out re-sorts and re-saves every finished parent
    # on each checkpoint, which grows quadratically when the parent is every user in the org.
    resumable: bool = True
    # Top-level row keys never written to the warehouse.
    excluded_fields: tuple[str, ...] = ()
    # Limit the first sync to the last N days instead of full history. Only used by
    # endpoints with a true time filter (System Log retention is bounded anyway).
    default_lookback_days: Optional[int] = None


OKTA_ENDPOINTS: dict[str, OktaEndpointConfig] = {
    # lastUpdated is the only incremental cursor offered for the filter endpoints: it is the
    # canonical, documented server-side filter attribute and it actually advances on edits.
    # `created` never changes, so it stays the stable partition key but is not a useful cursor.
    "users": OktaEndpointConfig(
        name="users",
        path="/users",
        incremental_fields=[_datetime_incremental_field("lastUpdated")],
        default_incremental_field="lastUpdated",
        incremental_param="filter",
        partition_key="created",
        page_size=200,
    ),
    "groups": OktaEndpointConfig(
        name="groups",
        path="/groups",
        incremental_fields=[_datetime_incremental_field("lastUpdated")],
        default_incremental_field="lastUpdated",
        incremental_param="filter",
        partition_key="created",
        page_size=200,
    ),
    "applications": OktaEndpointConfig(
        name="applications",
        path="/apps",
        # The Apps API `filter` only supports status, user.id, group.id and
        # credentials.signing.kid — not lastUpdated — so there is no server-side time
        # filter and this is full-refresh only.
        partition_key="created",
        page_size=200,
    ),
    "logs": OktaEndpointConfig(
        name="logs",
        path="/logs",
        # System Log events are immutable; `published` is the only sensible cursor.
        incremental_fields=[_datetime_incremental_field("published")],
        default_incremental_field="published",
        incremental_param="since",
        partition_key="published",
        primary_keys=["uuid"],
        page_size=1000,
        default_lookback_days=90,
    ),
    "group_rules": OktaEndpointConfig(
        name="group_rules",
        path="/groups/rules",
        # The group rules endpoint does not accept a server-side time filter, so this is
        # full-refresh only.
        partition_key="created",
        page_size=200,
    ),
    "user_types": OktaEndpointConfig(
        name="user_types",
        path="/meta/types/user",
        # Small, unpaginated metadata list. Full refresh only.
        page_size=200,
    ),
    # The child endpoints below take no server-side time filter, so they are full refresh only.
    # Child ids are only unique within their parent, so the parent id is part of every key.
    "group_members": OktaEndpointConfig(
        name="group_members",
        path="/groups/{groupId}/users",
        partition_key="created",
        primary_keys=["group_id", "id"],
        # Okta's default page size here is very large for historical reasons; 200 is its recommended limit.
        page_size=200,
        fanout=DependentEndpointConfig(
            parent_name="groups",
            resolve_param="groupId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "group_id"},
            # A parent deleted between the parent listing and its child fetch 404s.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "application_users": OktaEndpointConfig(
        name="application_users",
        path="/apps/{appId}/users",
        partition_key="created",
        primary_keys=["app_id", "id"],
        page_size=500,
        fanout=DependentEndpointConfig(
            parent_name="applications",
            resolve_param="appId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "app_id"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "application_groups": OktaEndpointConfig(
        name="application_groups",
        path="/apps/{appId}/groups",
        primary_keys=["app_id", "id"],
        page_size=200,
        fanout=DependentEndpointConfig(
            parent_name="applications",
            resolve_param="appId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "app_id"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "user_factors": OktaEndpointConfig(
        name="user_factors",
        path="/users/{userId}/factors",
        partition_key="created",
        primary_keys=["user_id", "id"],
        paginated=False,
        resumable=False,
        # A factor pending activation embeds its enrollment secret (e.g. the TOTP shared secret) and
        # links to its QR code. Neither belongs in queryable warehouse data.
        excluded_fields=("_embedded", "_links"),
        fanout=DependentEndpointConfig(
            parent_name="users",
            resolve_param="userId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "user_id"},
            # The child takes no page size, so the parent's `limit` is set here instead.
            parent_params={"limit": 200},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

ENDPOINTS = tuple(OKTA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in OKTA_ENDPOINTS.items()
}
