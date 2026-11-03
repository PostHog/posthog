from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, IncrementalFieldType


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
    # Row keys never written to the warehouse. A dotted name drops a nested key.
    excluded_fields: tuple[str, ...] = ()
    # False for list endpoints that paginate by Link header but whose `limit` maximum is undocumented.
    send_limit: bool = True
    # The custom-role endpoints wrap rows in an object and put the next page in `_links.next.href`.
    data_selector: Optional[str] = None
    next_link_in_body: bool = False
    # Policy list endpoints require a `type`, so the table reads every policy type in turn.
    per_policy_type: bool = False
    # Copies a nested value to a top-level column, for keys Okta only returns inside an object.
    lifted_fields: dict[str, tuple[str, ...]] = field(default_factory=dict)
    description: Optional[str] = None
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
        description="Only syncs the last 90 days on initial sync",
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
    "policies": OktaEndpointConfig(
        name="policies",
        path="/policies",
        partition_key="created",
        send_limit=False,
        per_policy_type=True,
    ),
    "policy_rules": OktaEndpointConfig(
        name="policy_rules",
        path="/policies/{policyId}/rules",
        partition_key="created",
        primary_keys=["policy_id", "id"],
        send_limit=False,
        per_policy_type=True,
        # The policy type loop checkpoints between types instead.
        resumable=False,
        fanout=DependentEndpointConfig(
            parent_name="policies",
            resolve_param="policyId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "policy_id"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "devices": OktaEndpointConfig(
        name="devices",
        path="/devices",
        # The `search` filter reads an eventually consistent index, so it cannot carry a watermark.
        partition_key="created",
        page_size=200,
        description="Requires Okta Identity Engine",
    ),
    "device_users": OktaEndpointConfig(
        name="device_users",
        path="/devices/{deviceId}/users",
        partition_key="created",
        primary_keys=["device_id", "user_id"],
        paginated=False,
        resumable=False,
        lifted_fields={"user_id": ("user", "id")},
        description="Requires Okta Identity Engine",
        fanout=DependentEndpointConfig(
            parent_name="devices",
            resolve_param="deviceId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "device_id"},
            parent_params={"limit": 200},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "custom_roles": OktaEndpointConfig(
        name="custom_roles",
        path="/iam/roles",
        partition_key="created",
        send_limit=False,
        data_selector="roles",
        next_link_in_body=True,
    ),
    "user_role_assignments": OktaEndpointConfig(
        name="user_role_assignments",
        path="/users/{userId}/roles",
        partition_key="created",
        primary_keys=["user_id", "id"],
        paginated=False,
        resumable=False,
        fanout=DependentEndpointConfig(
            parent_name="users",
            resolve_param="userId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "user_id"},
            parent_params={"limit": 200},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "group_role_assignments": OktaEndpointConfig(
        name="group_role_assignments",
        path="/groups/{groupId}/roles",
        partition_key="created",
        primary_keys=["group_id", "id"],
        paginated=False,
        fanout=DependentEndpointConfig(
            parent_name="groups",
            resolve_param="groupId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "group_id"},
            parent_params={"limit": 200},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "identity_providers": OktaEndpointConfig(
        name="identity_providers",
        path="/idps",
        partition_key="created",
        page_size=200,
        # OIDC and social IdPs return their client secret here.
        excluded_fields=("protocol.credentials",),
    ),
    "identity_provider_users": OktaEndpointConfig(
        name="identity_provider_users",
        path="/idps/{idpId}/users",
        partition_key="created",
        primary_keys=["idp_id", "id"],
        page_size=200,
        fanout=DependentEndpointConfig(
            parent_name="identity_providers",
            resolve_param="idpId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "idp_id"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

# Every value of the PolicyType enum in the Management API spec. An org rejects a type it does not
# have (for example ACCESS_POLICY on Classic Engine), and the source skips that type.
POLICY_TYPES: tuple[str, ...] = (
    "OKTA_SIGN_ON",
    "PASSWORD",
    "MFA_ENROLL",
    "IDP_DISCOVERY",
    "ACCESS_POLICY",
    "PROFILE_ENROLLMENT",
    "POST_AUTH_SESSION",
    "ENTITY_RISK",
    "DEVICE_SIGNAL_COLLECTION",
    "SESSION_VIOLATION_DETECTION",
    "CLIENT_UPDATE",
    "IDENTITY_CLAIM_SOURCING",
)

ENDPOINTS = tuple(OKTA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in OKTA_ENDPOINTS.items()
}
