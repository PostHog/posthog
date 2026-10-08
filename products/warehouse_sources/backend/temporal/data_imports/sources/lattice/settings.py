from dataclasses import dataclass, field
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)

# Lattice's default page size is only 10; always request the max of 100.
PAGE_SIZE = 100

# Reviews and reviewees only exist per review cycle, so they fan out over `/v1/reviewCycles`.
REVIEW_CYCLE_FANOUT = DependentEndpointConfig(
    parent_name="review_cycles",
    resolve_param="review_cycle_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "review_cycle_id"},
)


@dataclass
class LatticeEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    fanout: DependentEndpointConfig | None = None
    page_size: int = PAGE_SIZE
    incremental_fields: list[Any] = field(default_factory=list)
    default_incremental_field: str | None = None


# The Lattice Talent API v1 has no server-side incremental filters on any list
# endpoint (Fivetran's connector re-imports every table each sync for the same
# reason), so every stream is an honest full refresh.
LATTICE_ENDPOINTS: dict[str, LatticeEndpointConfig] = {
    "users": LatticeEndpointConfig(
        name="users",
        path="/v1/users",
    ),
    "departments": LatticeEndpointConfig(
        name="departments",
        path="/v1/departments",
    ),
    "goals": LatticeEndpointConfig(
        name="goals",
        path="/v1/goals",
    ),
    "goal_updates": LatticeEndpointConfig(
        name="goal_updates",
        path="/v1/goals/updates",
        # The numeric `id` is not documented as unique; `entityId` is the update's UUID.
        primary_keys=["entityId"],
    ),
    "feedbacks": LatticeEndpointConfig(
        name="feedbacks",
        path="/v1/feedbacks",
    ),
    "review_cycles": LatticeEndpointConfig(
        name="review_cycles",
        path="/v1/reviewCycles",
    ),
    "reviewees": LatticeEndpointConfig(
        name="reviewees",
        path="/v1/reviewCycle/{review_cycle_id}/reviewees",
        fanout=REVIEW_CYCLE_FANOUT,
    ),
    "reviews": LatticeEndpointConfig(
        name="reviews",
        path="/v1/reviewCycle/{review_cycle_id}/reviews",
        # Unlike reviewees, reviews have no fetch-by-id endpoint, so the id is only known
        # to be unique within its cycle.
        primary_keys=["review_cycle_id", "id"],
        fanout=REVIEW_CYCLE_FANOUT,
    ),
    "tags": LatticeEndpointConfig(
        name="tags",
        path="/v1/tags",
    ),
    "updates": LatticeEndpointConfig(
        name="updates",
        path="/v1/updates",
    ),
}

ENDPOINTS = tuple(LATTICE_ENDPOINTS.keys())
