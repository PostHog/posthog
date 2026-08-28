from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
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
    primary_key: str = "id"
    page_size: int = 200
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
        primary_key="uuid",
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
}

ENDPOINTS = tuple(OKTA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in OKTA_ENDPOINTS.items()
}
