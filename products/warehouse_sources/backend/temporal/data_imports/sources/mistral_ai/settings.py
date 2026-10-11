from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class MistralAIEndpointConfig:
    name: str
    path: str
    # Stable creation-time field used for datetime partitioning (never a mutable field like
    # updated_at/modified_at). `created` on models, `created_at` everywhere else.
    partition_key: str
    # Preferred location of the list in the response body. Most endpoints wrap rows in
    # `{"data": [...]}`; /v1/agents and /v1/conversations return a bare JSON array (`data_key=None`).
    # `_extract_rows` also accepts a bare array regardless of this setting, so an endpoint that
    # returns the un-wrapped shape still syncs rather than silently dropping every row.
    data_key: Optional[str] = "data"
    # /v1/models is the only list endpoint with no pagination — a single GET returns everything.
    paginated: bool = True
    page_size: int = 100
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    # Server-side incremental filter. Only set where the API documents a genuine created-time
    # filter that drops older rows (verified against the published OpenAPI spec: the param is a
    # date-time filter described as "results for previous creation times are not displayed").
    incremental_field: Optional[str] = None
    incremental_field_type: IncrementalFieldType = IncrementalFieldType.Integer
    created_after_param: Optional[str] = None
    # Some endpoints let us force ascending creation order so the incremental watermark advances
    # monotonically. (param_name, ascending_value) — e.g. batch jobs accept order_by=created.
    order_by: Optional[tuple[str, str]] = None
    extra_params: dict[str, str] = field(default_factory=dict)
    # "page" walks 0-indexed `page`/`page_size` until an empty page. "cursor" is the observability
    # search feed: a POST whose body nests rows and the next cursor under `data_key`.
    pagination: Literal["page", "cursor"] = "page"
    # Fan-out child endpoints: `path` holds a `{parent_id}` placeholder filled from each row of the
    # parent endpoint, and the parent id is stamped onto child rows under `parent_id_field`.
    parent: Optional[str] = None
    parent_id_field: Optional[str] = None
    # How the watermark is persisted for incremental endpoints. "asc" stages the running max after
    # every page (safe only when the API returns rows in ascending creation order); "desc" persists
    # the watermark once at the end of a successful sync, so an endpoint whose page order we can't
    # guarantee never advances the watermark past rows still waiting on later pages.
    sort_mode: Literal["asc", "desc"] = "asc"

    @property
    def supports_incremental(self) -> bool:
        return self.created_after_param is not None

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        if self.incremental_field is None:
            return []
        return [
            {
                "label": self.incremental_field,
                # Displayed/treated as a datetime. The underlying column is a Unix timestamp (integer
                # seconds) for the jobs' `created_at`, and an ISO date-time for observability `start_time`.
                "type": IncrementalFieldType.DateTime,
                "field": self.incremental_field,
                "field_type": self.incremental_field_type,
            }
        ]


MISTRAL_AI_ENDPOINTS: dict[str, MistralAIEndpointConfig] = {
    # Available base models plus this workspace's fine-tuned models. Unpaginated single GET; each
    # card carries a Unix `created` timestamp.
    "models": MistralAIEndpointConfig(
        name="models",
        path="/v1/models",
        partition_key="created",
        paginated=False,
    ),
    # Files uploaded to the workspace (fine-tuning datasets, batch inputs, etc.).
    "files": MistralAIEndpointConfig(
        name="files",
        path="/v1/files",
        partition_key="created_at",
    ),
    # Fine-tuning jobs with status, hyperparameters, trained-token counts, and timestamps.
    # Incremental via created_after. The endpoint exposes no sort parameter, so page order is not
    # guaranteed; use "desc" semantics so the watermark is only persisted once the whole run
    # succeeds, never advancing past older jobs sitting on a later page.
    "fine_tuning_jobs": MistralAIEndpointConfig(
        name="fine_tuning_jobs",
        path="/v1/fine_tuning/jobs",
        partition_key="created_at",
        incremental_field="created_at",
        created_after_param="created_after",
        sort_mode="desc",
    ),
    # Batch inference jobs with request counts and statuses. Incremental via created_after; we pass
    # order_by=created to force ascending order (the API defaults to -created / newest-first).
    "batch_jobs": MistralAIEndpointConfig(
        name="batch_jobs",
        path="/v1/batch/jobs",
        partition_key="created_at",
        incremental_field="created_at",
        created_after_param="created_after",
        order_by=("order_by", "created"),
    ),
    # Beta. Agents defined in the workspace. Returns a bare JSON array; created_at is an ISO string.
    # No created-time filter, so full refresh only.
    "agents": MistralAIEndpointConfig(
        name="agents",
        path="/v1/agents",
        partition_key="created_at",
        data_key=None,
        should_sync_default=False,
    ),
    # Beta. Conversations. Returns a bare JSON array of model/agent conversations; ISO created_at.
    "conversations": MistralAIEndpointConfig(
        name="conversations",
        path="/v1/conversations",
        partition_key="created_at",
        data_key=None,
        should_sync_default=False,
    ),
    # Beta. Document libraries (retrieval knowledge bases); ISO created_at. Kept on the wrapped
    # default, but `_extract_rows` also accepts a bare array if the beta endpoint returns one.
    "libraries": MistralAIEndpointConfig(
        name="libraries",
        path="/v1/libraries",
        partition_key="created_at",
        should_sync_default=False,
    ),
    # Beta. Every entry (messages, function calls, tool executions, handoffs) of each conversation,
    # in the order appended. /history is a superset of /messages, so only /history is synced. Entry
    # ids are only documented within a conversation, so the key carries the conversation id.
    "conversation_entries": MistralAIEndpointConfig(
        name="conversation_entries",
        path="/v1/conversations/{parent_id}/history",
        partition_key="created_at",
        data_key="entries",
        paginated=False,
        primary_keys=["conversation_id", "id"],
        should_sync_default=False,
        parent="conversations",
        parent_id_field="conversation_id",
    ),
    # Beta. Documents uploaded to each library, with their processing status. No created-time filter.
    "library_documents": MistralAIEndpointConfig(
        name="library_documents",
        path="/v1/libraries/{parent_id}/documents",
        partition_key="created_at",
        primary_keys=["library_id", "id"],
        should_sync_default=False,
        extra_params={"sort_by": "created_at", "sort_order": "asc"},
        parent="libraries",
        parent_id_field="library_id",
    ),
    # Beta. Observability traces (one row per agent/workflow run) with latency, token and error
    # counts. `from` filters on the trace start time. The feed documents no ordering, so the
    # watermark is persisted only at the end of a successful run.
    "traces": MistralAIEndpointConfig(
        name="traces",
        path="/v1/observability/traces/search",
        partition_key="start_time",
        data_key="traces",
        page_size=100,
        primary_keys=["trace_id"],
        should_sync_default=False,
        incremental_field="start_time",
        incremental_field_type=IncrementalFieldType.DateTime,
        created_after_param="from",
        sort_mode="desc",
        pagination="cursor",
    ),
    # Beta. Observability spans across every trace. Span ids are only unique within a trace.
    "spans": MistralAIEndpointConfig(
        name="spans",
        path="/v1/observability/spans/search",
        partition_key="start_time",
        data_key="spans",
        page_size=100,
        primary_keys=["trace_id", "span_id"],
        should_sync_default=False,
        incremental_field="start_time",
        incremental_field_type=IncrementalFieldType.DateTime,
        created_after_param="from",
        sort_mode="desc",
        pagination="cursor",
    ),
}

ENDPOINTS = tuple(MISTRAL_AI_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in MISTRAL_AI_ENDPOINTS.items() if config.supports_incremental
}
