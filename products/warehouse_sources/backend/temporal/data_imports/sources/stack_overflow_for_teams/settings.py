from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# Every v3 list endpoint (except Answers, whose fan-out page size is set independently in
# fanout.py) caps `pageSize` at 100 - always request the max to minimise round trips.
PAGE_SIZE = 100


@dataclass
class StackOverflowForTeamsEndpointConfig:
    name: str
    path: str  # Path under /v3/teams/{team}, e.g. "/questions"
    # `sort`/`order` values valid for this endpoint's list action (per the v3 OpenAPI spec -
    # each resource has its own sort enum). Passed explicitly on every request so pagination
    # sees a stable order even though every endpoint here is full refresh.
    sort: Optional[str]
    order: Optional[str]
    # Stable creation-time field to partition by. None when the resource has no reliable
    # creation date (Users).
    partition_key: Optional[str] = "creationDate"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    page_size: int = PAGE_SIZE
    fanout: DependentEndpointConfig | None = None
    # No v3 list endpoint has a confirmed server-side timestamp filter (see INCREMENTAL_FIELDS
    # below), so every endpoint stays full refresh; these satisfy the fan-out helper's endpoint
    # protocol without advertising an incremental field.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None


STACK_OVERFLOW_FOR_TEAMS_ENDPOINTS: dict[str, StackOverflowForTeamsEndpointConfig] = {
    "Questions": StackOverflowForTeamsEndpointConfig(
        name="Questions",
        path="/questions",
        sort="creation",
        order="asc",
    ),
    "Answers": StackOverflowForTeamsEndpointConfig(
        name="Answers",
        path="/questions/{questionId}/answers",
        sort="creation",
        order="asc",
        # AnswerSummaryResponseModel already carries `questionId` on every row, but the answer
        # `id` is only documented as unique within its question, and this table aggregates
        # answers fanned out across every question - keep the parent id in the key defensively.
        primary_keys=["id", "questionId"],
        fanout=DependentEndpointConfig(
            parent_name="Questions",
            resolve_param="questionId",
            resolve_field="id",
            # The answers response already includes `questionId` natively, so no parent fields
            # need to be injected.
            include_from_parent=[],
            # Keep the parent (Questions) traversal in a stable order while fanning out.
            parent_params={"sort": "creation", "order": "asc"},
        ),
    ),
    "Articles": StackOverflowForTeamsEndpointConfig(
        name="Articles",
        path="/articles",
        sort="creation",
        order="asc",
    ),
    "Tags": StackOverflowForTeamsEndpointConfig(
        name="Tags",
        path="/tags",
        # TagsSortParameter uses "creationDate", not "creation".
        sort="creationDate",
        order="asc",
    ),
    "Users": StackOverflowForTeamsEndpointConfig(
        name="Users",
        path="/users",
        # UsersSortParameter documents only "reputation" - no creation-time sort is offered, so
        # ordering isn't guaranteed stable across pages; the users table is typically small
        # enough that this doesn't matter in practice.
        sort="reputation",
        order="asc",
        partition_key=None,
    ),
    "Collections": StackOverflowForTeamsEndpointConfig(
        name="Collections",
        path="/collections",
        sort="creation",
        order="asc",
    ),
}

ENDPOINTS = tuple(STACK_OVERFLOW_FOR_TEAMS_ENDPOINTS.keys())

# The v3 API documents `from`/`to` date-time filters on Questions/Articles/Collections, but
# doesn't specify which field they filter against, and it can't be confirmed against a live
# team without a customer PAT - so every endpoint ships full refresh for now. Revisit once the
# filter semantics are verified against a real team.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in ENDPOINTS}
