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
    # v1 resources use Mongo-style `_id`; v2 and Directory Insights use `id`. System Insights rows
    # carry no unique identifier, so they sync without a primary key.
    primary_key: str | None = "_id"
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
    # Newer v2 services (alerts, identity risk) wrap the rows of a page in an object under this
    # key, e.g. {"alerts": [...], "count": n}, instead of returning a bare array.
    data_key: str | None = None
    # Page size to request; None uses the console's default cap of 100. System Insights allows
    # up to 10,000 rows per page and returns many small rows per device.
    page_size: int | None = None

    @property
    def primary_keys(self) -> list[str] | None:
        if self.primary_key is None:
            return None
        if self.parent_id_column:
            return [self.parent_id_column, self.primary_key]
        return [self.primary_key]


# Core directory resources plus the Directory Insights activity event log. The REST entity
# endpoints (users, systems, groups, applications) expose no server-side "updated since"
# filter, so they sync as full refresh. Directory Insights events accept a server-side
# start_time/end_time window, so that stream syncs incrementally on `timestamp`. The graph
# association tables (memberships and bindings) fan out per parent and have no timestamps,
# so they also sync as full refresh. Policies, alerts, identity risk events, and System Insights
# device facts are mutable (statuses, resolutions, re-collected snapshots) and their list
# endpoints have no "updated since" filter, so they sync as full refresh too.
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
    "policies": JumpcloudEndpointConfig(
        name="policies",
        path="/api/v2/policies",
        api="v2",
        primary_key="id",
    ),
    "policy_results": JumpcloudEndpointConfig(
        name="policy_results",
        path="/api/v2/policyresults",
        api="v2",
        primary_key="id",
        partition_key="startedAt",
    ),
    # Fans out per policy rather than per system (`/systems/{id}/policystatuses`): both return
    # the latest result per policy and system, and an organization has far fewer policies.
    "policy_statuses": JumpcloudEndpointConfig(
        name="policy_statuses",
        path="/api/v2/policies/{parent_id}/policystatuses",
        api="v2",
        primary_key="id",
        parent="policies",
        parent_id_column="policy_id",
    ),
    "alerts": JumpcloudEndpointConfig(
        name="alerts",
        path="/api/v2/alerts",
        api="v2",
        primary_key="objectId",
        partition_key="createdAt",
        data_key="alerts",
    ),
    # Occurrences have no identifier of their own, so they're keyed on the alert and occurrence time.
    "alert_occurrences": JumpcloudEndpointConfig(
        name="alert_occurrences",
        path="/api/v2/alerts/{parent_id}/occurrences",
        api="v2",
        primary_key="occurredAt",
        parent="alerts",
        parent_id_column="alert_id",
        data_key="alertOccurrences",
    ),
    "identity_risk_events": JumpcloudEndpointConfig(
        name="identity_risk_events",
        path="/api/v2/identityrisk/events",
        api="v2",
        primary_key="objectId",
        partition_key="createdAt",
        data_key="riskEvents",
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

# A curated subset of the System Insights (osquery) tables: software inventory, patching, and
# security posture. Credential-adjacent tables (shadow, authorized_keys, user_ssh_keys) are left out.
SYSTEM_INSIGHTS_TABLES = (
    "alf",
    "apps",
    "battery",
    "bitlocker_info",
    "browser_plugins",
    "chrome_extensions",
    "disk_encryption",
    "disk_info",
    "firefox_addons",
    "kernel_info",
    "linux_packages",
    "logged_in_users",
    "os_version",
    "patches",
    "programs",
    "safari_extensions",
    "secureboot",
    "sip_config",
    "system_info",
    "uptime",
    "usb_devices",
    "users",
    "windows_security_center",
    "windows_security_products",
)

JUMPCLOUD_ENDPOINTS.update(
    {
        f"system_insights_{table}": JumpcloudEndpointConfig(
            name=f"system_insights_{table}",
            path=f"/api/v2/systeminsights/{table}",
            api="v2",
            primary_key=None,
            page_size=1000,
        )
        for table in SYSTEM_INSIGHTS_TABLES
    }
)

ENDPOINTS = tuple(JUMPCLOUD_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in JUMPCLOUD_ENDPOINTS.items()
}
