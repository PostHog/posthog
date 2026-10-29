from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField

# Roark exposes no server-side timestamp filter on any list endpoint (only client-side `sortBy`
# ordering plus an opaque `after` cursor), so every table syncs as a full refresh. Incremental sync
# would page through the entire resource each run regardless, so it buys nothing here.
PaginationMode = Literal["cursor", "offset", "none"]


@dataclass(frozen=True)
class RoarkEndpointConfig:
    name: str
    path: str
    pagination: PaginationMode
    # Field to partition by. Must be a STABLE creation-time field (never an `updated_at`), so a row's
    # partition doesn't move between syncs. `None` disables partitioning for the endpoint.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Max page size the endpoint accepts (Roark caps most list endpoints at 50, calls/chats/issues at
    # 100). `0` means the endpoint takes no pagination params (single unpaginated response).
    max_page_size: int = 50
    # Only `call` and `chat` accept `sortBy`/`sortDirection`. Passing a stable ascending sort keeps
    # pagination from skipping or duplicating rows if records are inserted mid-sync.
    sort_by: Optional[str] = None
    sort_direction: Optional[str] = None
    # Order rows actually arrive in, reported to the pipeline. Full-refresh only uses this defensively;
    # `issue` is fixed newest-first by the API and can't be reordered.
    sort_mode: SortMode = "asc"
    should_sync_default: bool = True
    # Set on a child endpoint that is fetched once per row of a parent endpoint.
    fanout: Optional[DependentEndpointConfig] = None

    # The shared fan-out helper reads these three members from every endpoint config.
    @property
    def page_size(self) -> int:
        return self.max_page_size

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        return []

    @property
    def default_incremental_field(self) -> Optional[str]:
        return None


# A parent row deleted between the parent listing and the child request answers 404; skip it.
_SKIP_MISSING_PARENT: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}]


def _per_call() -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name="call",
        resolve_param="callId",
        resolve_field="id",
        include_from_parent=["id"],
        parent_field_renames={"id": "callId"},
        child_response_actions=_SKIP_MISSING_PARENT,
    )


ROARK_ENDPOINTS: dict[str, RoarkEndpointConfig] = {
    "call": RoarkEndpointConfig(
        name="call",
        path="/call",
        pagination="cursor",
        partition_key="startedAt",
        max_page_size=100,
        sort_by="createdAt",
        sort_direction="asc",
    ),
    "chat": RoarkEndpointConfig(
        name="chat",
        path="/chat",
        pagination="cursor",
        partition_key="startTimestamp",
        max_page_size=100,
        sort_by="createdAt",
        sort_direction="asc",
    ),
    "agent": RoarkEndpointConfig(
        name="agent",
        path="/agent",
        pagination="cursor",
        partition_key="createdAt",
    ),
    "agent_endpoint": RoarkEndpointConfig(
        name="agent_endpoint",
        path="/agent/endpoint",
        pagination="cursor",
        partition_key="createdAt",
    ),
    "metric_definition": RoarkEndpointConfig(
        name="metric_definition",
        path="/metric/definitions",
        pagination="none",
        max_page_size=0,
    ),
    "metric_collection_job": RoarkEndpointConfig(
        name="metric_collection_job",
        path="/metric/collection-jobs",
        pagination="cursor",
        partition_key="createdAt",
    ),
    "issue": RoarkEndpointConfig(
        name="issue",
        path="/issue",
        pagination="offset",
        partition_key="createdAt",
        max_page_size=100,
        # The issue endpoint returns results newest-first with no way to reorder.
        sort_mode="desc",
    ),
    "simulation_scenario": RoarkEndpointConfig(
        name="simulation_scenario",
        path="/simulation/scenario",
        pagination="cursor",
        partition_key="createdAt",
    ),
    "persona": RoarkEndpointConfig(
        name="persona",
        path="/persona",
        pagination="cursor",
        partition_key="createdAt",
    ),
    "run_plan": RoarkEndpointConfig(
        name="run_plan",
        path="/simulation/plan",
        pagination="cursor",
        partition_key="createdAt",
    ),
    "simulation_plan_job": RoarkEndpointConfig(
        name="simulation_plan_job",
        path="/simulation/plan/jobs",
        pagination="cursor",
        partition_key="createdAt",
        # The plan-job resource keys on `simulationRunPlanJobId` rather than a generic `id`.
        primary_keys=["simulationRunPlanJobId"],
    ),
    "knowledge_base": RoarkEndpointConfig(
        name="knowledge_base",
        path="/knowledge-base",
        pagination="cursor",
        partition_key="createdAt",
    ),
    # The three endpoints below make one request per parent row on every sync, so they are off by
    # default. None of them is paginated, and none has a server-side time filter.
    "call_metric": RoarkEndpointConfig(
        name="call_metric",
        path="/call/{callId}/metrics",
        pagination="none",
        max_page_size=0,
        # One row per metric definition per call; the scored values stay nested under `values`
        # because `value` is a number, a boolean or a string depending on the metric type.
        primary_keys=["callId", "metricDefinitionId"],
        should_sync_default=False,
        fanout=_per_call(),
    ),
    "call_transcript": RoarkEndpointConfig(
        name="call_transcript",
        path="/call/{callId}/transcript",
        pagination="none",
        max_page_size=0,
        # Transcript entries carry no id, so a row is keyed on its position in the call.
        primary_keys=["callId", "entryIndex"],
        should_sync_default=False,
        fanout=_per_call(),
    ),
    "metric_collection_job_metric_value": RoarkEndpointConfig(
        name="metric_collection_job_metric_value",
        path="/metric/collection-jobs/{jobId}/metric-values",
        pagination="none",
        max_page_size=0,
        primary_keys=["jobId", "metricDefinitionId"],
        should_sync_default=False,
        fanout=DependentEndpointConfig(
            parent_name="metric_collection_job",
            resolve_param="jobId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "jobId"},
            child_response_actions=_SKIP_MISSING_PARENT,
        ),
    ),
}

ENDPOINTS = tuple(ROARK_ENDPOINTS.keys())
