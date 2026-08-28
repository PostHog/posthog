from dataclasses import dataclass, field

# Environment-scoped API keys mean one key syncs one Vellum environment (Development/Staging/Production).
# Self-hosted/VPC customers have account-specific base URLs, but the managed cloud API lives here.
VELLUM_BASE_URL = "https://api.vellum.ai/v1"


@dataclass
class VellumEndpointConfig:
    name: str
    # Path relative to VELLUM_BASE_URL. Fan-out endpoints carry a `{deployment_id}` placeholder.
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable created-style field used to partition the Delta table. Never a mutable field like
    # `last_deployed_on` / `last_uploaded_at`, which would rewrite partitions on every sync.
    partition_key: str | None = None
    # Value passed as `?ordering=` for a deterministic page order across the offset walk. Left None
    # when the resource exposes no stable orderable timestamp (Vellum silently accepts unknown
    # ordering values, so we only send one we can reason about).
    ordering: str | None = None
    should_sync_default: bool = True
    # Fan out over every workflow deployment, hitting `path` (with `{deployment_id}`) per parent to
    # pull its execution history. The parent id is injected into each child row under
    # `parent_id_field` so the composite primary key stays unique table-wide.
    fan_out_over_workflow_deployments: bool = False
    parent_id_field: str | None = None


VELLUM_ENDPOINTS: dict[str, VellumEndpointConfig] = {
    # Deployed workflows. `created` is immutable; `last_deployed_on` is not, so it is never the partition key.
    "workflow_deployments": VellumEndpointConfig(
        name="workflow_deployments",
        path="/workflow-deployments",
        partition_key="created",
        ordering="created",
    ),
    # Deployed prompts (Vellum calls these simply "deployments").
    "prompt_deployments": VellumEndpointConfig(
        name="prompt_deployments",
        path="/deployments",
        partition_key="created",
        ordering="created",
    ),
    # RAG document indexes.
    "document_indexes": VellumEndpointConfig(
        name="document_indexes",
        path="/document-indexes",
        partition_key="created",
        ordering="created",
    ),
    # Documents uploaded for indexing. Exposes only `last_uploaded_at` (mutable on re-upload), so no
    # partition key and no ordering — full refresh with merge dedup on `id`.
    "documents": VellumEndpointConfig(
        name="documents",
        path="/documents",
    ),
    # Per-workflow-deployment execution history — the richest historical stream (per-execution inputs,
    # outputs, timing). Fans out one paginated request per workflow deployment. `span_id` is unique per
    # execution but the key is composite with the parent id so rows aggregated across deployments stay
    # unique table-wide. Opt-in (off by default) because it multiplies API calls by the deployment count.
    "workflow_execution_events": VellumEndpointConfig(
        name="workflow_execution_events",
        path="/workflow-deployments/{deployment_id}/execution-events",
        primary_keys=["workflow_deployment_id", "span_id"],
        partition_key="start",
        should_sync_default=False,
        fan_out_over_workflow_deployments=True,
        parent_id_field="workflow_deployment_id",
    ),
}

ENDPOINTS = tuple(VELLUM_ENDPOINTS.keys())
