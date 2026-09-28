from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

_CREATED_AT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "createdAt",
        "type": IncrementalFieldType.DateTime,
        "field": "createdAt",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass(frozen=True)
class DrataEndpointConfig:
    name: str
    # Path template; fan-out endpoints carry a `{parent_id}` placeholder.
    path: str
    # Parent endpoint to walk for fan-out children (e.g. controls fan out over workspaces).
    fan_out_parent: Optional[str] = None
    # Column the parent's id is injected under on each child row (camelCase, matching the API).
    # Child rows don't carry their parent id natively, and child ids aren't documented as unique
    # beyond their parent, so fan-out primary keys must include this column.
    fan_out_parent_id_column: Optional[str] = None
    # Path placeholder -> parent row field that fills it. The default binds the single
    # `{parent_id}` placeholder to the parent's `id`; a child nested two levels deep binds one
    # placeholder per ancestor id carried on the parent row.
    fan_out_path_params: dict[str, str] = field(default_factory=lambda: {"parent_id": "id"})
    # Further parent row fields copied onto each child row -> the column they land under. Used by
    # deeper fan-outs whose primary key needs a grandparent id too.
    fan_out_extra_parent_columns: dict[str, str] = field(default_factory=dict)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation timestamp used for datetime partitioning (never an updated-at style field).
    partition_key: Optional[str] = "createdAt"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Maps an incremental field name to the server-side query param that filters on it.
    incremental_param_by_field: dict[str, str] = field(default_factory=dict)
    default_incremental_field: Optional[str] = None
    # `sort` value passed on every request. Every v2 list endpoint accepts `createdAt` (most also
    # accept `updatedAt`); a stable creation-order sort keeps cursor pages consistent mid-sync.
    sort: str = "createdAt"
    # Results per page; the v2 API allows 1-500 (default 50).
    page_size: int = 250
    # Extra query params sent on every request to this endpoint.
    extra_params: dict[str, str] = field(default_factory=dict)
    # False leaves the table deselected by default in the schema picker. Used for the risk tables,
    # which are gated on Drata's Risk Management Pro feature and 403 on accounts without it.
    should_sync_default: bool = True


# Drata public API v2 list endpoints (https://developers.drata.com/openapi/reference/v2/overview/).
# Only `events` exposes a server-side timestamp filter (`createdAtStartDate`), so it is the only
# incremental-capable endpoint; the rest are compliance inventories synced via full refresh.
DRATA_ENDPOINTS: dict[str, DrataEndpointConfig] = {
    "workspaces": DrataEndpointConfig(
        name="workspaces",
        path="/workspaces",
    ),
    "users": DrataEndpointConfig(
        name="users",
        path="/users",
    ),
    "user_assigned_policies": DrataEndpointConfig(
        name="user_assigned_policies",
        path="/users/{parent_id}/assigned-policies",
        fan_out_parent="users",
        fan_out_parent_id_column="userId",
        primary_keys=["userId", "id"],
    ),
    "personnel": DrataEndpointConfig(
        name="personnel",
        path="/personnel",
    ),
    "devices": DrataEndpointConfig(
        name="devices",
        path="/devices",
    ),
    "assets": DrataEndpointConfig(
        name="assets",
        path="/assets",
    ),
    "vendors": DrataEndpointConfig(
        name="vendors",
        path="/vendors",
    ),
    "policies": DrataEndpointConfig(
        name="policies",
        path="/policies",
    ),
    "events": DrataEndpointConfig(
        name="events",
        path="/events",
        incremental_fields=_CREATED_AT_INCREMENTAL_FIELDS,
        incremental_param_by_field={"createdAt": "createdAtStartDate"},
        default_incremental_field="createdAt",
    ),
    "controls": DrataEndpointConfig(
        name="controls",
        path="/workspaces/{parent_id}/controls",
        fan_out_parent="workspaces",
        fan_out_parent_id_column="workspaceId",
        primary_keys=["workspaceId", "id"],
    ),
    "monitoring_tests": DrataEndpointConfig(
        name="monitoring_tests",
        path="/workspaces/{parent_id}/monitoring-tests",
        fan_out_parent="workspaces",
        fan_out_parent_id_column="workspaceId",
        primary_keys=["workspaceId", "id"],
    ),
    "monitoring_test_failures": DrataEndpointConfig(
        name="monitoring_test_failures",
        # `{parent_id}` binds the parent's `testId`, not its `id`: Drata documents `id` as an
        # internal record identifier no public endpoint accepts.
        path="/workspaces/{workspaceId}/monitoring-tests/{parent_id}/failures",
        fan_out_parent="monitoring_tests",
        fan_out_parent_id_column="monitoringTestId",
        fan_out_path_params={"parent_id": "testId", "workspaceId": "workspaceId"},
        fan_out_extra_parent_columns={"workspaceId": "workspaceId"},
        # A failure row is one cloud resource failing one test; `id` is the provider's resource id,
        # unique only within the test that flagged it.
        primary_keys=["workspaceId", "monitoringTestId", "id"],
        # Failure rows carry no timestamp at all, so there is nothing stable to partition on.
        partition_key=None,
        # Excluded findings are omitted by default; keep them so the `status` column tells the
        # whole story instead of the row silently disappearing when someone dismisses it. Tags
        # only arrive when asked for, and they are what attributes a failing resource to a team.
        extra_params={"includeExclusions": "true", "expand[]": "tags"},
    ),
    "tasks": DrataEndpointConfig(
        name="tasks",
        path="/workspaces/{parent_id}/tasks",
        fan_out_parent="workspaces",
        fan_out_parent_id_column="workspaceId",
        primary_keys=["workspaceId", "id"],
    ),
    "evidence_library": DrataEndpointConfig(
        name="evidence_library",
        path="/workspaces/{parent_id}/evidence-library",
        fan_out_parent="workspaces",
        fan_out_parent_id_column="workspaceId",
        primary_keys=["workspaceId", "id"],
    ),
    "frameworks": DrataEndpointConfig(
        name="frameworks",
        path="/workspaces/{parent_id}/frameworks",
        fan_out_parent="workspaces",
        fan_out_parent_id_column="workspaceId",
        primary_keys=["workspaceId", "id"],
    ),
    "framework_requirements": DrataEndpointConfig(
        name="framework_requirements",
        path="/workspaces/{parent_id}/framework-requirements",
        fan_out_parent="workspaces",
        fan_out_parent_id_column="workspaceId",
        primary_keys=["workspaceId", "id"],
    ),
    "risk_registers": DrataEndpointConfig(
        name="risk_registers",
        path="/risk-registers",
        should_sync_default=False,
    ),
    "risks": DrataEndpointConfig(
        name="risks",
        path="/risk-registers/{parent_id}/risks",
        fan_out_parent="risk_registers",
        fan_out_parent_id_column="riskRegisterId",
        primary_keys=["riskRegisterId", "id"],
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(DRATA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DRATA_ENDPOINTS.items() if config.incremental_fields
}
