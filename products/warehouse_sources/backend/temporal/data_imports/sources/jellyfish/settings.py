from dataclasses import dataclass, field
from typing import Any, Literal, Optional

# How far back the windowed analytics endpoints sync. The export API has no pagination — data is
# scoped purely by `start_date`/`end_date` windows — so every sync walks this many month windows.
# Rows are small monthly aggregates, so two years stays cheap (one request per month per endpoint).
DEFAULT_LOOKBACK_MONTHS = 24

# `window_mode` controls how an endpoint is scoped by date:
# - "month": one request per calendar-month window (aggregate/metric endpoints); rows get
#   `window_start_date` / `window_end_date` injected so each aggregate keeps its period.
# - "full": a single request covering the whole lookback range (entity-shaped rows like
#   deliverables, where a wide window returns discrete records, not per-period aggregates).
# - None: no date params (small reference lists).
WindowMode = Optional[Literal["month", "full"]]

# Parent lists a fan-out endpoint iterates. Each parent's id is passed as `JellyfishFanOut.param`.
# - "work_categories": slugs from `delivery/work_categories`.
# - "engineers": person ids from `people/list_engineers`.
# - "teams": team ids from the whole `teams/list_teams` tree.
# - "deliverables": deliverable ids from `delivery/work_category_contents` in every work category.
FanOutParent = Literal["work_categories", "engineers", "teams", "deliverables"]


@dataclass(frozen=True)
class JellyfishFanOut:
    parent: FanOutParent
    # Query param the parent id goes in. Rows also get it injected under this name, so each row
    # keeps the entity it was exported for.
    param: str


@dataclass(frozen=True)
class JellyfishEndpointConfig:
    name: str
    path: str  # relative to https://app.jellyfish.co/endpoints/export/v0/
    window_mode: WindowMode = None
    # Static query params the endpoint requires (beyond auth/format/date windows).
    params: dict[str, Any] = field(default_factory=dict)
    # Top-level response key wrapping the row list, when known (e.g. `deliverables`). The row
    # extractor falls back to auto-detecting a single list-of-dicts value when this is unset.
    data_key: str | None = None
    # When set, the endpoint is called once per parent entity (see `FanOutParent`).
    fan_out: JellyfishFanOut | None = None
    primary_keys: list[str] | None = None
    # Only month-windowed endpoints partition — on the injected, stable `window_start_date`.
    partition_key: str | None = None


# The endpoints a Jellyfish user actually wants in a warehouse, cross-referenced against the
# official Jellyfish-AI/jellyfish-mcp wrapper (no Airbyte/Fivetran connector exists): reference
# lists (engineers, teams, work categories), R&D allocation breakdowns, delivery deliverables, and
# company-level metrics. Endpoints that require a per-entity id (person/team metrics, work
# category allocations, deliverable scope history) fan out over the matching parent list.
JELLYFISH_ENDPOINTS: dict[str, JellyfishEndpointConfig] = {
    "engineers": JellyfishEndpointConfig(
        name="engineers",
        path="people/list_engineers",
        primary_keys=["id"],
    ),
    "teams": JellyfishEndpointConfig(
        name="teams",
        path="teams/list_teams",
        # `hierarchy_level` is required; level 1 + include_children walks the whole team tree.
        params={"hierarchy_level": 1, "include_children": "true"},
        data_key="teams",
        primary_keys=["id"],
    ),
    "work_categories": JellyfishEndpointConfig(
        name="work_categories",
        path="delivery/work_categories",
        primary_keys=["slug"],
    ),
    "allocations_by_person": JellyfishEndpointConfig(
        name="allocations_by_person",
        path="allocations/details/by_person",
        window_mode="month",
        partition_key="window_start_date",
    ),
    "allocations_by_team": JellyfishEndpointConfig(
        name="allocations_by_team",
        path="allocations/details/by_team",
        # `team_hierarchy_level` is required; 1 is the top organizational level.
        params={"team_hierarchy_level": 1},
        window_mode="month",
        partition_key="window_start_date",
    ),
    "allocations_by_investment_category": JellyfishEndpointConfig(
        name="allocations_by_investment_category",
        path="allocations/details/investment_category",
        window_mode="month",
        partition_key="window_start_date",
    ),
    "company_metrics": JellyfishEndpointConfig(
        name="company_metrics",
        path="metrics/company_metrics",
        window_mode="month",
        partition_key="window_start_date",
    ),
    "unlinked_pull_requests": JellyfishEndpointConfig(
        name="unlinked_pull_requests",
        path="metrics/unlinked_pull_requests",
        window_mode="month",
        partition_key="window_start_date",
    ),
    "deliverables": JellyfishEndpointConfig(
        name="deliverables",
        path="delivery/work_category_contents",
        window_mode="full",
        data_key="deliverables",
        fan_out=JellyfishFanOut(parent="work_categories", param="work_category_slug"),
    ),
    "allocations_by_work_category": JellyfishEndpointConfig(
        name="allocations_by_work_category",
        path="allocations/details/work_category",
        window_mode="month",
        fan_out=JellyfishFanOut(parent="work_categories", param="work_category_slug"),
        partition_key="window_start_date",
    ),
    "allocations_by_work_category_person": JellyfishEndpointConfig(
        name="allocations_by_work_category_person",
        path="allocations/details/work_category/by_person",
        window_mode="month",
        fan_out=JellyfishFanOut(parent="work_categories", param="work_category_slug"),
        partition_key="window_start_date",
    ),
    "allocations_by_work_category_team": JellyfishEndpointConfig(
        name="allocations_by_work_category_team",
        path="allocations/details/work_category/by_team",
        params={"team_hierarchy_level": 1},
        window_mode="month",
        fan_out=JellyfishFanOut(parent="work_categories", param="work_category_slug"),
        partition_key="window_start_date",
    ),
    "person_metrics": JellyfishEndpointConfig(
        name="person_metrics",
        path="metrics/person_metrics",
        window_mode="month",
        fan_out=JellyfishFanOut(parent="engineers", param="person_id"),
        partition_key="window_start_date",
    ),
    "team_metrics": JellyfishEndpointConfig(
        name="team_metrics",
        path="metrics/team_metrics",
        window_mode="month",
        fan_out=JellyfishFanOut(parent="teams", param="team_id"),
        partition_key="window_start_date",
    ),
    "deliverable_scope_and_effort_history": JellyfishEndpointConfig(
        name="deliverable_scope_and_effort_history",
        path="delivery/scope_and_effort_history",
        # One wide window per deliverable; `unit=week` returns one row per week of history.
        params={"unit": "week"},
        window_mode="full",
        fan_out=JellyfishFanOut(parent="deliverables", param="deliverable_id"),
    ),
}

ENDPOINTS = tuple(JELLYFISH_ENDPOINTS.keys())
