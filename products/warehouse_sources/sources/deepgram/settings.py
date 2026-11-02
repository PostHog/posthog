from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@frozen
class DeepgramEndpointConfig:
    name: str
    # Path suffix appended to /v1/projects/{project_id} for the per-project fan-out endpoints.
    # Empty string is the top-level /v1/projects list itself (see `is_project_list`).
    path: str
    # Key in the JSON response body that holds the list of rows (Deepgram wraps every list in an
    # envelope, e.g. {"projects": [...]}, {"requests": [...]}). "$" selects the whole body, for the
    # endpoints whose payload is several parallel collections rather than one list; a row expander in
    # deepgram.py then splits it into rows.
    data_key: str
    primary_keys: list[str]
    # Stable creation-time field used for datetime partitioning. Never a mutable field.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    supports_incremental: bool = False
    # page/limit pagination — only the requests log supports it; the other endpoints return a full
    # unpaginated array.
    paginated: bool = False
    # The top-level /v1/projects list. It seeds the fan-out and is not itself fanned out per project.
    is_project_list: bool = False
    # Sub-object to lift into the row root before keying/partitioning (e.g. /keys nests the key under
    # "api_key"). None means the row is used as-is.
    flatten_key: Optional[str] = None
    # Dimension columns of an aggregate endpoint. When set, the row gets a derived `grouping_key`
    # joining their values, so the primary key identifies the slice a row covers however Deepgram
    # groups the results. The dimensions themselves are null under some groupings and cannot key.
    grouping_dimensions: list[str] = field(default_factory=list)
    should_sync_default: bool = True


DEEPGRAM_ENDPOINTS: dict[str, DeepgramEndpointConfig] = {
    "projects": DeepgramEndpointConfig(
        name="projects",
        path="",
        data_key="projects",
        primary_keys=["project_id"],
        is_project_list=True,
    ),
    "members": DeepgramEndpointConfig(
        name="members",
        path="/members",
        data_key="members",
        # member_id is only unique within a project, so key on the pair to stay unique table-wide.
        primary_keys=["project_id", "member_id"],
    ),
    "keys": DeepgramEndpointConfig(
        name="keys",
        path="/keys",
        data_key="api_keys",
        primary_keys=["project_id", "api_key_id"],
        partition_key="created",
        flatten_key="api_key",
    ),
    "balances": DeepgramEndpointConfig(
        name="balances",
        path="/balances",
        data_key="balances",
        primary_keys=["project_id", "balance_id"],
    ),
    "invites": DeepgramEndpointConfig(
        name="invites",
        path="/invites",
        data_key="invites",
        # Invites have no id; the invited email is unique per project.
        primary_keys=["project_id", "email"],
    ),
    # The request log is the highest-value stream: one row per inference request with model/feature
    # metadata, response code, and a `created` timestamp. It is the only endpoint with a genuine
    # server-side timestamp filter (`start`/`end` on `created`) and page/limit pagination, so it is
    # the only one synced incrementally.
    "requests": DeepgramEndpointConfig(
        name="requests",
        path="/requests",
        data_key="requests",
        primary_keys=["project_id", "request_id"],
        partition_key="created",
        supports_incremental=True,
        paginated=True,
        incremental_fields=[
            {
                "label": "created",
                "type": IncrementalFieldType.DateTime,
                "field": "created",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # The project's model catalogue: every model the project can call, public and non-public, so the
    # model ids carried on request rows resolve to a name, version and language. The response is two
    # parallel arrays ("stt", "tts") rather than one list, so the whole body is selected and split
    # into rows. The account-wide /v1/models lists only the public subset of the same models.
    "models": DeepgramEndpointConfig(
        name="models",
        path="/models",
        data_key="$",
        primary_keys=["project_id", "uuid"],
    ),
    # Transcription, TTS and agent usage per project over a date range. `start`/`end` filter
    # server-side on whole days, so the sync is incremental on the group's start date; the boundary
    # day is re-read each run and the merge collapses it, which keeps an in-progress day current.
    "usage_breakdown": DeepgramEndpointConfig(
        name="usage_breakdown",
        path="/usage/breakdown",
        data_key="results",
        primary_keys=["project_id", "start", "end", "grouping_key"],
        flatten_key="grouping",
        grouping_dimensions=["accessor", "endpoint", "feature_set", "models", "method", "tags", "deployment"],
        supports_incremental=True,
        incremental_fields=[
            {
                "label": "start",
                "type": IncrementalFieldType.Date,
                "field": "start",
                "field_type": IncrementalFieldType.Date,
            },
        ],
    ),
    # Spend per project over the same date range, which is what turns a balance into an explanation
    # of where the credit went.
    "billing_breakdown": DeepgramEndpointConfig(
        name="billing_breakdown",
        path="/billing/breakdown",
        data_key="results",
        primary_keys=["project_id", "start", "end", "grouping_key"],
        flatten_key="grouping",
        grouping_dimensions=["accessor", "deployment", "line_item", "tags"],
        supports_incremental=True,
        incremental_fields=[
            {
                "label": "start",
                "type": IncrementalFieldType.Date,
                "field": "start",
                "field_type": IncrementalFieldType.Date,
            },
        ],
    ),
    # The models, tags, processing methods and features the project used in the period, which are
    # the dimensions a usage breakdown can be sliced by. The response is one object of parallel
    # lists, so it is emitted long: one row per value, labelled with the list it came from.
    "usage_fields": DeepgramEndpointConfig(
        name="usage_fields",
        path="/usage/fields",
        data_key="$",
        primary_keys=["project_id", "field", "value"],
    ),
    # The same idea for billing: the accessors, deployments, tags and line items the project was
    # billed on in the period.
    "billing_fields": DeepgramEndpointConfig(
        name="billing_fields",
        path="/billing/fields",
        data_key="$",
        primary_keys=["project_id", "field", "value"],
    ),
}

ENDPOINTS = tuple(DEEPGRAM_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DEEPGRAM_ENDPOINTS.items()
}
