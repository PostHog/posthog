from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# The list endpoints accept a `limit`; the docs don't state a hard maximum, so 100 keeps each page
# reasonably sized while minimising round trips.
PAGE_SIZE = 100


@dataclass(frozen=True)
class HuntrEndpointConfig:
    name: str
    path: str
    # Huntr object IDs are globally unique within an organization, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # False for endpoints that return a bare JSON array with no `next` cursor and take no `limit`.
    paginated: bool = True
    fanout: DependentEndpointConfig | None = None
    page_size: int = PAGE_SIZE
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None


# Huntr Organization API list endpoints (https://docs.huntr.co). All are full-refresh only: only the
# jobs endpoint documents a created_after/created_before filter, and no resource exposes a reliable
# updated_after cursor, so there is no incremental cursor to advance safely across every stream (see
# the implementing-warehouse-sources skill).
HUNTR_ENDPOINTS: dict[str, HuntrEndpointConfig] = {
    "members": HuntrEndpointConfig(name="members", path="/members"),
    "advisors": HuntrEndpointConfig(name="advisors", path="/advisors"),
    "candidates": HuntrEndpointConfig(name="candidates", path="/candidates"),
    "jobs": HuntrEndpointConfig(name="jobs", path="/jobs"),
    "job_posts": HuntrEndpointConfig(name="job_posts", path="/job-posts"),
    "employers": HuntrEndpointConfig(name="employers", path="/employers"),
    "activities": HuntrEndpointConfig(name="activities", path="/activities"),
    "actions": HuntrEndpointConfig(name="actions", path="/actions"),
    "activity_categories": HuntrEndpointConfig(name="activity_categories", path="/activity-categories"),
    "tags": HuntrEndpointConfig(name="tags", path="/tags", paginated=False),
    # One request per candidate. The response is an object keyed by action type, which huntr.py
    # explodes into one row per (candidate, action type).
    "candidate_action_metrics": HuntrEndpointConfig(
        name="candidate_action_metrics",
        path="/candidates/{candidate_id}/action-metrics",
        primary_keys=["candidate_id", "action_type"],
        fanout=DependentEndpointConfig(
            parent_name="candidates",
            resolve_param="candidate_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "candidate_id"},
            parent_params={"limit": PAGE_SIZE},
            # A candidate deleted between the candidates listing and its metrics fetch must not fail the sync.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

ENDPOINTS = tuple(HUNTR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
