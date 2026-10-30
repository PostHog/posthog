from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# The list endpoints accept a `limit`; the largest page minimises round trips.
PAGE_SIZE = 100


@dataclass(frozen=True)
class RecruiteeEndpointConfig:
    name: str
    # Path relative to https://api.recruitee.com/c/<company_id> (leading slash included).
    path: str
    # Top-level key in the JSON response that holds the list of records (matches the resource name).
    data_key: str
    # Recruitee object IDs are unique within a company, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    pagination: Literal["offset", "page"] = "offset"
    params: dict[str, str] = field(default_factory=dict)
    fanout: Optional[DependentEndpointConfig] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)

    @property
    def default_incremental_field(self) -> Optional[str]:
        return None

    @property
    def page_size(self) -> int:
        return PAGE_SIZE


# Recruitee company-level list endpoints. All are full refresh only: Recruitee exposes no
# documented server-side `updated_after`/`created_after` cursor on these listings (the official
# Airbyte connector is likewise full-refresh only), so there is no incremental cursor to advance.
RECRUITEE_ENDPOINTS: dict[str, RecruiteeEndpointConfig] = {
    "candidates": RecruiteeEndpointConfig(name="candidates", path="/candidates", data_key="candidates"),
    "offers": RecruiteeEndpointConfig(name="offers", path="/offers", data_key="offers"),
    "departments": RecruiteeEndpointConfig(name="departments", path="/departments", data_key="departments"),
    "placements": RecruiteeEndpointConfig(name="placements", path="/placements", data_key="placements"),
    "locations": RecruiteeEndpointConfig(
        name="locations",
        path="/locations",
        data_key="locations",
        # /locations documents `page` + `limit`, not `offset`.
        pagination="page",
        # `scope=all` keeps archived locations that older offers still reference; `view_mode=full`
        # adds the translations and the active offer counters.
        params={"scope": "all", "view_mode": "full"},
    ),
    "candidate_notes": RecruiteeEndpointConfig(
        name="candidate_notes",
        path="/candidates/{candidate_id}/notes",
        data_key="notes",
        # Notes are fetched per candidate, so the parent candidate ID is part of the key.
        primary_keys=["candidate_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="candidates",
            resolve_param="candidate_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "candidate_id"},
            # A candidate deleted between the candidates listing and its notes fetch returns 404.
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

ENDPOINTS = tuple(RECRUITEE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
