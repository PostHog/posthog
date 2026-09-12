from dataclasses import dataclass, field
from datetime import timedelta

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class AutomoxEndpointConfig:
    # Console API path, relative to https://console.automox.com/api. May contain an
    # `{org_id}` placeholder resolved at sync time.
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-style timestamp used for datetime partitioning (never a field that churns).
    partition_key: str | None = None
    # Key the row list is nested under when the response is wrapped (e.g. policy_runs `data`).
    # None means the endpoint returns a bare JSON array.
    data_selector: str | None = None
    # Automox caps `limit` at 500 for Console API list endpoints (policy_runs allows more, but
    # 500 keeps response sizes bounded).
    page_size: int = 500
    # `False` for endpoints that answer with the whole collection and take no page/limit params.
    # Sending them anyway risks looping on the same rows if the API ignores them.
    paginated: bool = True
    # Pass the resolved numeric organization ID as the `o` query param. Most Console API list
    # endpoints take it; without it the API falls back to the key's default organization.
    needs_org_id_param: bool = False
    # Name of the query param carrying the organization UUID (Policy History endpoints use
    # `org=<uuid>` instead of `o=<numeric id>`).
    org_uuid_param: str | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Server-side time filter query param backing incremental sync. None means the endpoint has
    # no server-side filter and syncs as full refresh only.
    incremental_param: str | None = None
    # `True` when the filter param only accepts a date (YYYY-MM-DD) rather than a full timestamp.
    incremental_param_is_date: bool = False
    # Safety overlap subtracted from the incremental watermark on every run; re-pulled rows are
    # deduped on the primary key by the merge.
    incremental_lookback: timedelta | None = None
    # Extra query params sent on every request (e.g. an explicit sort).
    extra_params: dict[str, str] = field(default_factory=dict)
    sort_mode: SortMode = "asc"
    # When True, keep only the single configured organization's row. `/orgs` lists every
    # organization the API key can access, so without this the table would expose metadata for
    # organizations the source owner never selected.
    restrict_to_org: bool = False
    # Nested list fields to trim to the resolved organization, mapping the field name to the key on
    # each entry carrying the org id. The `o` param scopes which rows are listed, but per-row
    # membership metadata (a user's `orgs[]`, their org-tagged `rbac_roles[]`) still carries other
    # organizations the source owner never selected.
    org_scoped_list_fields: dict[str, str] = field(default_factory=dict)
    # Set when the endpoint is only reachable per parent resource, so the sync walks the parent
    # list first and calls this endpoint once per parent row.
    fan_out: "AutomoxFanOutConfig | None" = None


@dataclass
class AutomoxFanOutConfig:
    # List endpoint walked to enumerate the parents. It does not have to be a synced table.
    parent: AutomoxEndpointConfig
    # Field on each parent row substituted into the child path.
    parent_field: str
    # Placeholder in the child path replaced with `parent_field`'s value.
    placeholder: str
    # Parent field -> column added to every child row. Child rows aggregate across all parents, so
    # the parent identifier both joins the table back to its parent and completes the primary key.
    include_from_parent: dict[str, str]


# Parent of a fan-out endpoint that is not itself a synced table: an action set is one ingestion of
# a vulnerability report, only useful here to reach its issues.
_ACTION_SETS_PARENT = AutomoxEndpointConfig(
    path="/orgs/{org_id}/remediations/action-sets",
    data_selector="data",
)

# The devices endpoint doubles as the fan-out parent for per-device detail endpoints, so both walk
# exactly the same device list.
_DEVICES_ENDPOINT = AutomoxEndpointConfig(
    path="/servers",
    partition_key="create_time",
    needs_org_id_param=True,
)


AUTOMOX_ENDPOINTS: dict[str, AutomoxEndpointConfig] = {
    # Per-device hardware, health, network, security and system inventory, one row per collected
    # attribute. Automox answers with a nested category tree per device and the categories present
    # vary by OS and by the customer's Automox tier, so the tree is flattened into attribute rows.
    "device_inventory": AutomoxEndpointConfig(
        path="/device-details/orgs/{org_uuid}/devices/{device_uuid}/inventory",
        primary_keys=["device_uuid", "category", "sub_category", "name"],
        paginated=False,
        fan_out=AutomoxFanOutConfig(
            parent=_DEVICES_ENDPOINT,
            parent_field="uuid",
            placeholder="{device_uuid}",
            include_from_parent={"uuid": "device_uuid", "id": "device_id"},
        ),
    ),
    # Core device inventory. No server-side updated-since filter exists, so full refresh only.
    "devices": _DEVICES_ENDPOINT,
    # Console activity log. `startDate` is a server-side date filter, so incremental sync on
    # `create_time` genuinely reduces the pages fetched. The API does not document the sort
    # order of results, so `sort_mode="desc"` makes the pipeline persist the watermark only
    # when a sync completes instead of checkpointing per batch on an unverified ordering.
    "events": AutomoxEndpointConfig(
        path="/events",
        partition_key="create_time",
        needs_org_id_param=True,
        incremental_fields=[_datetime_incremental_field("create_time")],
        incremental_param="startDate",
        incremental_param_is_date=True,
        # `startDate` has date granularity and the docs don't say whether the boundary day is
        # included, so re-pull an extra day and let the merge dedupe on `id`.
        incremental_lookback=timedelta(days=1),
        sort_mode="desc",
    ),
    # Organizations the API key can access. Tiny table, full refresh. `/orgs` returns every
    # accessible organization, so restrict the table to the one this source is configured for.
    "organizations": AutomoxEndpointConfig(
        path="/orgs",
        partition_key="create_time",
        restrict_to_org=True,
    ),
    # All software packages across all devices in the organization, including patch status and
    # severity. The docs don't state whether the package record `id` is unique beyond its device,
    # so include `server_id` in the key to be safe.
    "packages": AutomoxEndpointConfig(
        path="/orgs/{org_id}/packages",
        primary_keys=["id", "server_id"],
        partition_key="create_time",
    ),
    "policies": AutomoxEndpointConfig(
        path="/policies",
        partition_key="create_time",
        needs_org_id_param=True,
    ),
    # Policy History API v2: one row per policy execution with per-status device counts.
    # `start_time` is a server-side timestamp filter and the endpoint accepts an explicit
    # ascending sort, so incremental sync is fully supported.
    "policy_runs": AutomoxEndpointConfig(
        path="/policy-history/policy-runs",
        primary_keys=["policy_uuid", "execution_token"],
        partition_key="run_time",
        data_selector="data",
        org_uuid_param="org",
        incremental_fields=[_datetime_incremental_field("run_time")],
        incremental_param="start_time",
        # A run's per-device result counts keep updating while devices report back, so re-pull a
        # day of runs each sync; the merge dedupes on the primary key.
        incremental_lookback=timedelta(hours=24),
        extra_params={"sort": "run_time:asc"},
        sort_mode="asc",
    ),
    # Per-policy device compliance counts, the headline number on the Automox dashboard. The
    # endpoint answers with every policy's stats in one array and takes no pagination params.
    "policy_stats": AutomoxEndpointConfig(
        path="/policystats",
        primary_keys=["organization_id", "policy_id"],
        needs_org_id_param=True,
        paginated=False,
    ),
    # Hosts named in an uploaded vulnerability report that Automox could not match to a managed
    # device, per remediation action set.
    "remediation_issues": AutomoxEndpointConfig(
        path="/orgs/{org_id}/remediations/action-sets/{action_set_id}/issues",
        primary_keys=["action_set_id", "id"],
        data_selector="data",
        fan_out=AutomoxFanOutConfig(
            parent=_ACTION_SETS_PARENT,
            parent_field="id",
            placeholder="{action_set_id}",
            include_from_parent={"id": "action_set_id"},
        ),
    ),
    "server_groups": AutomoxEndpointConfig(
        path="/servergroups",
        needs_org_id_param=True,
    ),
    "users": AutomoxEndpointConfig(
        path="/users",
        needs_org_id_param=True,
        # User records embed the user's full org memberships and org-tagged roles regardless of the
        # `o` scope, so trim both to the organization this source syncs.
        org_scoped_list_fields={"orgs": "id", "rbac_roles": "organization_id"},
    ),
}

ENDPOINTS = tuple(AUTOMOX_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in AUTOMOX_ENDPOINTS.items()
}
