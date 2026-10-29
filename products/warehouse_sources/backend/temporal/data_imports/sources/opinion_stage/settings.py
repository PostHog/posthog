from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# JSON:API `page[size]`. The API does not document a hard maximum, so a moderate page keeps the
# per-page payload bounded while minimising round trips.
PAGE_SIZE = 100


@frozen
class OpinionStageEndpointConfig:
    name: str
    path: str
    # JSON:API resource objects carry a top-level `id`, unique within the account, so it is a safe
    # primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    page_size: int = PAGE_SIZE
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    fanout: DependentEndpointConfig | None = None


def _per_item() -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name="items",
        resolve_param="item_id",
        resolve_field="id",
        include_from_parent=["id"],
        parent_field_renames={"id": "item_id"},
        # An item removed between the item listing and its child request answers 404. That item
        # has no rows to sync, so it must not fail the items that remain.
        child_response_actions=[{"status_code": 404, "action": "ignore"}],
    )


# Opinion Stage Public Result API list endpoints. `items` is the account-level collection.
# `responses` and `questions` are listed once per item.
#
# All are full-refresh only: although the docs mention date-range filtering, the filter parameter
# names are not defined in the OpenAPI spec, so there is no incremental cursor we can advance safely
# (see the implementing-warehouse-sources skill).
OPINION_STAGE_ENDPOINTS: dict[str, OpinionStageEndpointConfig] = {
    "items": OpinionStageEndpointConfig(name="items", path="/api/v2/items"),
    # The spec does not say that a response or question id is unique across items, so the item id
    # is part of the key.
    "responses": OpinionStageEndpointConfig(
        name="responses",
        path="/api/v2/items/{item_id}/responses",
        primary_keys=["item_id", "id"],
        fanout=_per_item(),
    ),
    "questions": OpinionStageEndpointConfig(
        name="questions",
        path="/api/v2/items/{item_id}/questions",
        primary_keys=["item_id", "id"],
        fanout=_per_item(),
    ),
}

ENDPOINTS = tuple(OPINION_STAGE_ENDPOINTS.keys())

# Every endpoint is full refresh only — the documented date-range filter has no parameter names in
# the OpenAPI spec, so there is no incremental cursor to advance safely. No endpoint has tracking
# fields, so build_endpoint_schemas marks them all full-refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
