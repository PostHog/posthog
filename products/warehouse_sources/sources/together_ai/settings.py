from dataclasses import dataclass, field
from typing import Any

from products.warehouse_sources.sources.sdk import DependentEndpointConfig

# Together AI platform API (https://docs.together.ai/reference). Every list endpoint is a single
# GET under https://api.together.xyz/v1 that returns the whole collection in one response — no
# pagination parameters and no server-side timestamp filters are documented (verified against the
# official Python SDK, which reads each list in one request). That means every table is full
# refresh only; collections are small per account, so a full fetch is cheap.
#
# Response envelopes vary per endpoint: fine-tunes/files/endpoints wrap rows in {"data": [...]},
# while batches/evaluations/models return a bare JSON array. Each endpoint pins its shape via
# `data_selector` so an unexpected body fails loud instead of syncing zero rows.

# The inference instance-type catalog is only served under /v2, outside the /v1 API root.
INSTANCE_TYPES_URL = "https://api.together.xyz/v2/public/inference-instance-types"

# Per-job endpoints under /fine-tunes/{id}/... fan out over every fine-tuning job. A job deleted
# between the parent listing and the child fetch returns 404, which must not fail the whole table.
FINE_TUNE_FANOUT = DependentEndpointConfig(
    parent_name="fine_tunes",
    resolve_param="id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "fine_tune_id"},
    child_response_actions=[{"status_code": 404, "action": "ignore"}],
)


@dataclass
class TogetherAIEndpointConfig:
    name: str
    # Path under the API root, e.g. "/fine-tunes", or an absolute URL for an endpoint outside it.
    path: str
    # Field to partition Delta files by. Must be a STABLE field (created timestamp, never updated_at).
    # None for a catalog whose rows carry no creation time.
    partition_key: str | None = "created_at"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Static query params sent with the request.
    params: dict[str, str] = field(default_factory=dict)
    # JSONPath to the row list in the response body. fine-tunes/files/endpoints wrap rows in
    # {"data": [...]} (data_selector="data"); batches/evaluations/models return a bare JSON array
    # (data_selector=None, the whole body is the list).
    data_selector: str | None = None
    fanout: DependentEndpointConfig | None = None
    # Row keys removed before the row is synced.
    excluded_fields: tuple[str, ...] = ()
    # Read by the shared fan-out helper; every Together list is unpaginated full refresh.
    incremental_fields: list[Any] = field(default_factory=list)
    default_incremental_field: str | None = None
    page_size: int = 0


TOGETHER_AI_ENDPOINTS: dict[str, TogetherAIEndpointConfig] = {
    "fine_tunes": TogetherAIEndpointConfig(name="fine_tunes", path="/fine-tunes", data_selector="data"),
    "batches": TogetherAIEndpointConfig(name="batches", path="/batches"),
    "files": TogetherAIEndpointConfig(name="files", path="/files", data_selector="data"),
    # Only the account's dedicated endpoint deployments — the unfiltered list also includes every
    # public serverless model, which duplicates the models table.
    "endpoints": TogetherAIEndpointConfig(
        name="endpoints", path="/endpoints", params={"type": "dedicated"}, data_selector="data"
    ),
    "evaluations": TogetherAIEndpointConfig(name="evaluations", path="/evaluations", primary_keys=["workflow_id"]),
    # The serverless model catalog: id, type, pricing, context length per model. Rows carry a
    # `created` unix timestamp instead of `created_at`.
    "models": TogetherAIEndpointConfig(name="models", path="/models", partition_key="created"),
    # Events carry no id; a job's events are unique by time, type and message.
    "fine_tune_events": TogetherAIEndpointConfig(
        name="fine_tune_events",
        path="/fine-tunes/{id}/events",
        primary_keys=["fine_tune_id", "created_at", "type", "message"],
        data_selector="data",
        fanout=FINE_TUNE_FANOUT,
    ),
    # A final checkpoint can list the merged model and the adapter at the same step, so the
    # display label is part of the key.
    "fine_tune_checkpoints": TogetherAIEndpointConfig(
        name="fine_tune_checkpoints",
        path="/fine-tunes/{id}/checkpoints",
        primary_keys=["fine_tune_id", "path", "checkpoint_type"],
        data_selector="data",
        fanout=FINE_TUNE_FANOUT,
    ),
    # `kube_config` is a credential for the customer's Kubernetes cluster, so it is never synced.
    "clusters": TogetherAIEndpointConfig(
        name="clusters",
        path="/compute/clusters",
        primary_keys=["cluster_id"],
        data_selector="clusters",
        excluded_fields=("kube_config",),
    ),
    "instance_types": TogetherAIEndpointConfig(
        name="instance_types", path=INSTANCE_TYPES_URL, partition_key=None, data_selector="data"
    ),
}

ENDPOINTS = tuple(TOGETHER_AI_ENDPOINTS.keys())
