from dataclasses import dataclass
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.Integer,  # FusionAuth instants are epoch millis
    }


@dataclass
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
}

ENDPOINTS = tuple(FUSIONAUTH_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FUSIONAUTH_ENDPOINTS.items()
}
