from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, ResponseAction

# Zenloop's list endpoints default to 50 rows per page; keep that size and paginate.
PER_PAGE = 50


# Mutable by choice: instances flow into `build_dependent_resource`'s `FanoutEndpointLike` mapping.
@dataclass(frozen=False)
class ZenloopEndpointConfig:
    name: str
    path: str
    # The list of rows lives under a named key in the response envelope
    # (e.g. {"surveys": [...], "meta": {...}}), and the key differs per endpoint. The detail
    # endpoints wrap one object under a key instead, which becomes a single row.
    response_key: str
    # Zenloop object IDs are unique within an account, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # A stable (never-rewritten) datetime field to partition by. Only set where the object
    # actually exposes a creation timestamp.
    partition_key: Optional[str] = None
    # "short_page": the account-level lists, sized with `per_page` and ended by a short page.
    # "total_pages": the answer lists, which document no page-size param but report
    # `meta.total_pages`. "single": a detail endpoint that returns one object.
    pagination: Literal["short_page", "total_pages", "single"] = "short_page"
    # Set for per-survey and per-survey-group resources that hang off an account-level list.
    fanout: Optional[DependentEndpointConfig] = None
    # Read by the fan-out helper. Every Zenloop endpoint is full refresh, so these stay empty.
    incremental_fields: list[Any] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    page_size: int = PER_PAGE


# Answers are listed oldest first so answers that arrive mid-sync land on the trailing pages
# instead of shifting rows across the page boundaries already read.
_ANSWER_PARAMS = {"order_by": "inserted_at", "order_type": "asc"}

# A survey or survey group deleted after the parent list was read answers 404. Skip that parent
# rather than failing the whole table.
_SKIP_DELETED_PARENT: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}]


def _fanout(parent_name: str, path_param: str, renamed_parent_id: str, **kwargs: Any) -> DependentEndpointConfig:
    # The answer paths take the parent's `public_hash_id`. Survey answers don't carry their
    # survey, and no answer carries its survey group, so the parent id is injected on every
    # answer row; the composite primary keys rely on it.
    return DependentEndpointConfig(
        parent_name=parent_name,
        resolve_param=path_param,
        resolve_field="public_hash_id",
        include_from_parent=["public_hash_id"],
        parent_field_renames={"public_hash_id": renamed_parent_id},
        parent_params={"per_page": PER_PAGE},
        child_response_actions=_SKIP_DELETED_PARENT,
        **kwargs,
    )


# Zenloop public API endpoints. All are full refresh only. The answer endpoints take a
# `date_from` filter on `inserted_at`, but an answer changes after it is created (the comment,
# additional answers, properties and sentiment labels arrive later, and answers can be updated),
# so a creation-time watermark would leave those rows stale.
ZENLOOP_ENDPOINTS: dict[str, ZenloopEndpointConfig] = {
    "surveys": ZenloopEndpointConfig(name="surveys", path="/surveys", response_key="surveys"),
    "survey_groups": ZenloopEndpointConfig(name="survey_groups", path="/survey_groups", response_key="survey_groups"),
    "properties": ZenloopEndpointConfig(name="properties", path="/properties", response_key="properties"),
    "survey_summaries": ZenloopEndpointConfig(
        name="survey_summaries",
        path="/surveys/{survey_id}",
        response_key="survey",
        primary_keys=["public_hash_id"],
        pagination="single",
        fanout=DependentEndpointConfig(
            parent_name="surveys",
            resolve_param="survey_id",
            resolve_field="public_hash_id",
            include_from_parent=[],
            parent_params={"per_page": PER_PAGE},
            child_response_actions=_SKIP_DELETED_PARENT,
        ),
    ),
    "survey_answers": ZenloopEndpointConfig(
        name="survey_answers",
        path="/surveys/{survey_id}/answers",
        response_key="answers",
        primary_keys=["survey_public_hash_id", "id"],
        partition_key="inserted_at",
        pagination="total_pages",
        fanout=_fanout("surveys", "survey_id", "survey_public_hash_id", child_params=_ANSWER_PARAMS),
    ),
    "survey_group_summaries": ZenloopEndpointConfig(
        name="survey_group_summaries",
        path="/survey_groups/{survey_group_id}",
        response_key="survey_group",
        primary_keys=["public_hash_id"],
        pagination="single",
        fanout=DependentEndpointConfig(
            parent_name="survey_groups",
            resolve_param="survey_group_id",
            resolve_field="public_hash_id",
            include_from_parent=[],
            parent_params={"per_page": PER_PAGE},
            child_response_actions=_SKIP_DELETED_PARENT,
        ),
    ),
    "survey_group_answers": ZenloopEndpointConfig(
        name="survey_group_answers",
        path="/survey_groups/{survey_group_id}/answers",
        response_key="answers",
        # One survey can sit in several groups, so the same answer appears once per group.
        primary_keys=["survey_group_public_hash_id", "id"],
        partition_key="inserted_at",
        pagination="total_pages",
        fanout=_fanout("survey_groups", "survey_group_id", "survey_group_public_hash_id", child_params=_ANSWER_PARAMS),
    ),
}

ENDPOINTS = tuple(ZENLOOP_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list] = {}
