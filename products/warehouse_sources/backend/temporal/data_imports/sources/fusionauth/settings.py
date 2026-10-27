from dataclasses import dataclass
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
        "field_type": IncrementalFieldType.Integer,  # FusionAuth instants are epoch millis
    }


@dataclass(frozen=True)
class FusionAuthEndpointConfig:
    name: str
    path: str
    # Key in the JSON response holding the list of rows (e.g. "users", "auditLogs").
    data_selector: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField]
    # Stable, immutable field to partition by. Never a field that mutates in place.
    partition_key: Optional[str] = None
    page_size: int = 100
    # "orderBy" -> the endpoint accepts an explicit `search.orderBy` string ("<field> ASC/DESC"),
    # so we can request ascending order and use a simple advancing watermark.
    # None -> the endpoint has no documented sort control; FusionAuth's default (and only
    # observed) behavior is newest-first, so incremental sync must scroll both directions
    # (see fusionauth.py's earliest/last value handling, mirroring the Stripe source).
    sort_mode: Literal["asc", "desc"] = "asc"
    # Elasticsearch-backed search endpoints (currently just user search) cap the standard
    # result window; None means no such cap is documented.
    maximum_offset: Optional[int] = None
    # Sent as `search.orderBy` on endpoints that document it (only used when sort_mode is "asc").
    order_by: str = "insertInstant ASC"
    # Dotted paths removed from every row before it is written, for secrets the API returns.
    exclude_fields: tuple[str, ...] = ()
    # "GET" endpoints are unpaginated lookups that return the whole collection in one response.
    method: Literal["POST", "GET"] = "POST"
    # GET only: also request the deactivated rows with `<param>=true`, deduplicated on `id`.
    inactive_param: Optional[str] = None
    # Elasticsearch-style searches (users, entities) take a `queryString` and `sortFields`
    # instead of the database searches' `orderBy`.
    query_string_search: bool = False
    # Emit one row per element of this list field of each parent row, instead of the row itself.
    explode_field: Optional[str] = None
    # Per-user child endpoints: one GET per user returned by the user search.
    fanout: Optional[DependentEndpointConfig] = None
    default_incremental_field: Optional[str] = None


# Search endpoints only: FusionAuth also has non-search read APIs (e.g. GET /api/user/{id})
# that aren't useful for a bulk warehouse sync, so they're intentionally excluded.
FUSIONAUTH_ENDPOINTS: dict[str, FusionAuthEndpointConfig] = {
    "Users": FusionAuthEndpointConfig(
        name="Users",
        path="/api/user/search",
        data_selector="users",
        primary_keys=["id"],
        # The Elasticsearch-backed queryString filter has no documented server-side timestamp
        # operator we can verify against a live instance, so this stays full refresh.
        incremental_fields=[],
        partition_key="insertInstant",
        page_size=100,
        sort_mode="asc",
        # Standard search window caps around 10k results (search_after/nextResults token
        # pagination for deeper scans is not implemented here).
        maximum_offset=9_900,
        query_string_search=True,
    ),
    "AuditLogs": FusionAuthEndpointConfig(
        name="AuditLogs",
        path="/api/system/audit-log/search",
        data_selector="auditLogs",
        primary_keys=["id"],
        incremental_fields=[_datetime_incremental_field("insertInstant")],
        partition_key="insertInstant",
        page_size=100,
        sort_mode="asc",
    ),
    "EventLogs": FusionAuthEndpointConfig(
        name="EventLogs",
        path="/api/system/event-log/search",
        data_selector="eventLogs",
        primary_keys=["id"],
        incremental_fields=[_datetime_incremental_field("insertInstant")],
        partition_key="insertInstant",
        page_size=100,
        sort_mode="asc",
    ),
    "LoginRecords": FusionAuthEndpointConfig(
        name="LoginRecords",
        path="/api/system/login-record/search",
        data_selector="logins",
        # Login records have no unique id field — identified by the combination of user,
        # application and instant (https://fusionauth.io/docs/apis/login/search).
        primary_keys=["userId", "applicationId", "instant"],
        incremental_fields=[_datetime_incremental_field("instant")],
        partition_key="instant",
        page_size=100,
        # No documented `orderBy`/sort control on this endpoint, so we can't assert ascending
        # order — assume FusionAuth's usual newest-first default like the other log endpoints.
        sort_mode="desc",
    ),
    # Database-backed lookup searches (not Elasticsearch) with no server-side timestamp filter, so
    # these are full refresh. `id ASC` keeps page boundaries stable while rows are being inserted.
    "Applications": FusionAuthEndpointConfig(
        name="Applications",
        path="/api/application/search",
        data_selector="applications",
        primary_keys=["id"],
        incremental_fields=[],
        partition_key="insertInstant",
        order_by="id ASC",
        exclude_fields=("oauthConfiguration.clientSecret",),
    ),
    "Tenants": FusionAuthEndpointConfig(
        name="Tenants",
        path="/api/tenant/search",
        data_selector="tenants",
        primary_keys=["id"],
        incremental_fields=[],
        partition_key="insertInstant",
        order_by="id ASC",
        exclude_fields=("captchaConfiguration.secretKey", "emailConfiguration.password"),
    ),
    "Groups": FusionAuthEndpointConfig(
        name="Groups",
        path="/api/group/search",
        data_selector="groups",
        primary_keys=["id"],
        incremental_fields=[],
        partition_key="insertInstant",
        order_by="id ASC",
    ),
    "GroupMembers": FusionAuthEndpointConfig(
        name="GroupMembers",
        path="/api/group/member/search",
        data_selector="members",
        primary_keys=["id"],
        incremental_fields=[],
        partition_key="insertInstant",
        order_by="id ASC",
    ),
    "Consents": FusionAuthEndpointConfig(
        name="Consents",
        path="/api/consent/search",
        data_selector="consents",
        primary_keys=["id"],
        incremental_fields=[],
        partition_key="insertInstant",
        order_by="id ASC",
    ),
    "Entities": FusionAuthEndpointConfig(
        name="Entities",
        path="/api/entity/search",
        data_selector="entities",
        primary_keys=["id"],
        incremental_fields=[],
        partition_key="insertInstant",
        maximum_offset=9_900,
        query_string_search=True,
        exclude_fields=("clientSecret",),
    ),
    "EntityGrants": FusionAuthEndpointConfig(
        name="EntityGrants",
        path="/api/entity/grant/search",
        data_selector="grants",
        primary_keys=["id"],
        incremental_fields=[],
        partition_key="insertInstant",
        # Grant search only orders by `insertInstant` or `name`.
        order_by="insertInstant ASC",
        exclude_fields=("entity.clientSecret",),
    ),
    # Registrations have no list API (only GET /api/user/registration/{userId}/{applicationId}), but
    # every user search result embeds the user's registrations, so they are read from there.
    "UserRegistrations": FusionAuthEndpointConfig(
        name="UserRegistrations",
        path="/api/user/search",
        data_selector="users",
        # A user has at most one registration per application.
        primary_keys=["userId", "applicationId"],
        incremental_fields=[],
        partition_key="insertInstant",
        maximum_offset=9_900,
        query_string_search=True,
        explode_field="registrations",
        exclude_fields=("tokens", "authenticationToken"),
    ),
    "UserConsents": FusionAuthEndpointConfig(
        name="UserConsents",
        path="/api/user/consent?userId={user_id}",
        data_selector="userConsents",
        primary_keys=["id"],
        incremental_fields=[],
        partition_key="insertInstant",
        method="GET",
        fanout=DependentEndpointConfig(
            parent_name="Users",
            resolve_param="user_id",
            resolve_field="id",
            include_from_parent=[],
            # A user deleted between the user search and this request.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "UserActionLogs": FusionAuthEndpointConfig(
        name="UserActionLogs",
        path="/api/user/action?userId={user_id}",
        data_selector="actions",
        primary_keys=["id"],
        incremental_fields=[],
        partition_key="insertInstant",
        method="GET",
        fanout=DependentEndpointConfig(
            parent_name="Users",
            resolve_param="user_id",
            resolve_field="id",
            include_from_parent=[],
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "UserActions": FusionAuthEndpointConfig(
        name="UserActions",
        path="/api/user-action",
        data_selector="userActions",
        primary_keys=["id"],
        incremental_fields=[],
        partition_key="insertInstant",
        method="GET",
        # Deactivated actions are listed separately, and past action logs can still reference them.
        inactive_param="inactive",
    ),
    "UserActionReasons": FusionAuthEndpointConfig(
        name="UserActionReasons",
        path="/api/user-action-reason",
        data_selector="userActionReasons",
        primary_keys=["id"],
        incremental_fields=[],
        partition_key="insertInstant",
        method="GET",
    ),
}

ENDPOINTS = tuple(FUSIONAUTH_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FUSIONAUTH_ENDPOINTS.items()
}
