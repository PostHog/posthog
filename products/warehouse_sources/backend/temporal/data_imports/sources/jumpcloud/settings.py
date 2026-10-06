from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class JumpcloudEndpointConfig:
    name: str
    path: str
    # Which JumpCloud API family serves the endpoint:
    #   "v1"       -> console API, GET, response wrapped as {"totalCount", "results": [...]}
    #   "v2"       -> console API v2, GET, response is a bare JSON array
    #   "insights" -> Directory Insights API, POST with a JSON query body, bare JSON array response
    api: Literal["v1", "v2", "insights"]
    # v1 resources use Mongo-style `_id`; v2 and Directory Insights use `id`.
    primary_key: str = "_id"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable, immutable field to partition by (creation/event time — never a mutating field).
    partition_key: str | None = None
    # Column to sort by while paginating. Sorting v1 list endpoints on the immutable `_id`
    # keeps limit/skip pagination stable as rows are inserted mid-sync. The v2 group
    # endpoints don't document a sort param, so they rely on the API's default ordering.
    sort: str | None = None
    # Fields to strip from every row before it's emitted, to keep secret-bearing fields out of
    # the warehouse where any table reader could see them. Each entry is a dotted path, so nested
    # fields can be redacted (e.g. `config.idpPrivateKey`); a bare name targets a top-level field.
    redact_keys: list[str] = field(default_factory=list)
    # Fan-out endpoints page through the `parent` endpoint and request `path` once per parent row,
    # with `{parent_id}` replaced by the parent's primary key. Child rows are graph objects whose
    # `id` is only unique within one parent, so the parent id is injected as `parent_id_column`
    # and joins the primary key.
    parent: str | None = None
    parent_id_column: str | None = None

    @property
    def primary_keys(self) -> list[str]:
        if self.parent_id_column:
            return [self.parent_id_column, self.primary_key]
        return [self.primary_key]


# Core directory resources plus the Directory Insights activity event log. The REST entity
# endpoints (users, systems, groups, applications) expose no server-side "updated since"
# filter, so they sync as full refresh. Directory Insights events accept a server-side
# start_time/end_time window, so that stream syncs incrementally on `timestamp`. The graph
# association tables (memberships and bindings) fan out per parent and have no timestamps,
# so they also sync as full refresh.
JUMPCLOUD_ENDPOINTS: dict[str, JumpcloudEndpointConfig] = {
    "users": JumpcloudEndpointConfig(
        name="users",
        path="/api/systemusers",
        api="v1",
        partition_key="created",
        sort="_id",
    ),
    "systems": JumpcloudEndpointConfig(
        name="systems",
        path="/api/systems",
        api="v1",
        partition_key="created",
        sort="_id",
    ),
    "user_groups": JumpcloudEndpointConfig(
        name="user_groups",
        path="/api/v2/usergroups",
        api="v2",
        primary_key="id",
    ),
    "system_groups": JumpcloudEndpointConfig(
        name="system_groups",
        path="/api/v2/systemgroups",
        api="v2",
        primary_key="id",
    ),
    "applications": JumpcloudEndpointConfig(
        name="applications",
        path="/api/applications",
        api="v1",
        # The application object documents no creation timestamp, so no datetime partitioning.
        sort="_id",
        # SSO application objects carry the SAML IdP signing key at `config.idpPrivateKey.value`.
        # Landing it in the warehouse would let any table reader forge assertions for apps that
        # trust it, so drop the whole private-key object before the row is emitted.
        redact_keys=["config.idpPrivateKey"],
    ),
    "user_group_members": JumpcloudEndpointConfig(
        name="user_group_members",
        path="/api/v2/usergroups/{parent_id}/membership",
        api="v2",
        primary_key="id",
        parent="user_groups",
        parent_id_column="group_id",
    ),
    "system_group_members": JumpcloudEndpointConfig(
        name="system_group_members",
        path="/api/v2/systemgroups/{parent_id}/membership",
        api="v2",
        primary_key="id",
        parent="system_groups",
        parent_id_column="group_id",
    ),
    "application_users": JumpcloudEndpointConfig(
        name="application_users",
        path="/api/v2/applications/{parent_id}/users",
        api="v2",
        primary_key="id",
        parent="applications",
        parent_id_column="application_id",
    ),
    "application_user_groups": JumpcloudEndpointConfig(
        name="application_user_groups",
        path="/api/v2/applications/{parent_id}/usergroups",
        api="v2",
        primary_key="id",
        parent="applications",
        parent_id_column="application_id",
    ),
    "system_users": JumpcloudEndpointConfig(
        name="system_users",
        path="/api/v2/systems/{parent_id}/users",
        api="v2",
        primary_key="id",
        parent="systems",
        parent_id_column="system_id",
    ),
    "events": JumpcloudEndpointConfig(
        name="events",
        path="/insights/directory/v1/events",
        api="insights",
        primary_key="id",
        # Events are immutable; their event time is the only sensible cursor and partition key.
        partition_key="timestamp",
        incremental_fields=[
            {
                "label": "timestamp",
                "type": IncrementalFieldType.DateTime,
                "field": "timestamp",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
    ),
}

ENDPOINTS = tuple(JUMPCLOUD_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in JUMPCLOUD_ENDPOINTS.items()
}
