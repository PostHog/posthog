from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# SonarQube caps `ps` (page size) at 500 on virtually every list endpoint.
PAGE_SIZE = 500

# /api/issues/search rejects any request where `p * ps` exceeds 10,000. To read past it we
# re-window using `createdAfter` set to the last issue's creation date and start paging again.
ISSUES_MAX_RESULTS = 10_000


def _created_at_incremental_fields() -> list[IncrementalField]:
    # /api/issues/search only exposes a creation-time server filter (`createdAfter`), keyed on
    # each issue's `creationDate`. There is no server-side "updated since" filter, so incremental
    # syncs pick up newly created issues; status changes on old issues are only reflected on a
    # full refresh.
    return [
        {
            "label": "creationDate",
            "type": IncrementalFieldType.DateTime,
            "field": "creationDate",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@dataclass
class SonarqubeEndpointConfig:
    name: str
    path: str  # Path under the instance base URL, e.g. "/api/issues/search"
    response_key: str  # Root key of the list in the JSON response
    supports_incremental: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field to partition by. None when the resource has no reliable created_at.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["key"])
    # Query params merged into every request for this endpoint (e.g. a required qualifier).
    extra_params: dict[str, str] = field(default_factory=dict)
    # issues/search hard-caps results at p*ps<=10000; walk past it by re-windowing on createdAfter.
    windowed_incremental: bool = False
    should_sync_default: bool = True


SONARQUBE_ENDPOINTS: dict[str, SonarqubeEndpointConfig] = {
    # Projects the token can see. /api/components/search with qualifiers=TRK lists projects and
    # only needs the browse permission, unlike /api/projects/search which requires Administer System.
    "projects": SonarqubeEndpointConfig(
        name="projects",
        path="/api/components/search",
        response_key="components",
        extra_params={"qualifiers": "TRK"},
    ),
    # Metric definitions — a small reference set that changes rarely, so full refresh each run.
    "metrics": SonarqubeEndpointConfig(
        name="metrics",
        path="/api/metrics/search",
        response_key="metrics",
    ),
    # Coding rules catalog — reference data used to interpret issues. Full refresh.
    "rules": SonarqubeEndpointConfig(
        name="rules",
        path="/api/rules/search",
        response_key="rules",
    ),
    # Issues (code smells, bugs, vulnerabilities). The core time series. `createdAfter` filters
    # server-side on creationDate; sorting ascending by CREATION_DATE lets us both sync
    # incrementally and re-window past the 10,000-result ceiling.
    "issues": SonarqubeEndpointConfig(
        name="issues",
        path="/api/issues/search",
        response_key="issues",
        supports_incremental=True,
        incremental_fields=_created_at_incremental_fields(),
        partition_key="creationDate",
        windowed_incremental=True,
    ),
    # Users. /api/users/search requires Administer System permission, so it's off by default —
    # a token without it can still sync everything else.
    "users": SonarqubeEndpointConfig(
        name="users",
        path="/api/users/search",
        response_key="users",
        primary_keys=["login"],
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(SONARQUBE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SONARQUBE_ENDPOINTS.items()
}
