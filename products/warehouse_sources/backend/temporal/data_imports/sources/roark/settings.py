from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SortMode

# Roark exposes no server-side timestamp filter on any list endpoint (only client-side `sortBy`
# ordering plus an opaque `after` cursor), so every table syncs as a full refresh. Incremental sync
# would page through the entire resource each run regardless, so it buys nothing here.
PaginationMode = Literal["cursor", "offset", "none"]


@dataclass
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
}

ENDPOINTS = tuple(ROARK_ENDPOINTS.keys())
