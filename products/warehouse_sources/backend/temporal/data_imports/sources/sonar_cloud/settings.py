from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField

# SonarQube Cloud v1 web API host per region. The token and organization are region-bound, so the
# host the user picks decides which of these we hit. v2 (api.sonarcloud.io / api.sonarqube.us) is
# gradually replacing v1, but v1 is still the mature, documented surface for these resources.
REGION_HOSTS: dict[str, str] = {
    "eu": "https://sonarcloud.io/api",
    "us": "https://sonarqube.us/api",
}

# v1 search endpoints page via `p`/`ps` (max 500) and hard-cap the total result set at 10000 rows.
# We ask for the largest page and stop once the cap is reached; slicing past it would need date/facet
# windowing, which the v1 surface doesn't offer uniformly.
MAX_PAGE_SIZE = 500
RESULT_CAP = 10000


@dataclass
class SonarCloudEndpointConfig:
    name: str
    # v1 path relative to `<host>/api`, e.g. "issues/search".
    path: str
    # Key in the JSON response holding the row list (SonarQube Cloud wraps rows differently per resource).
    data_key: str
    primary_keys: list[str] = field(default_factory=lambda: ["key"])
    # Most resources are scoped to a single organization; metric definitions are global.
    requires_organization: bool = True
    # Stable creation-time field to partition by. Never an updated_at-style field, which would rewrite
    # partitions every sync. `None` disables partitioning for the endpoint.
    partition_key: Optional[str] = None
    # Some resources (quality gates) return a flat, unpaginated list.
    paginated: bool = True
    should_sync_default: bool = True


# Endpoint catalog. Mirrors the streams the existing Airbyte SonarCloud connector ships (projects,
# issues, metrics) plus quality gates, all reachable with just an organization key. Every stream is
# full refresh: SonarQube Cloud exposes no uniform server-side update cursor, so there is no reliable
# incremental field to advertise (see the source docstring).
SONAR_CLOUD_ENDPOINTS: dict[str, SonarCloudEndpointConfig] = {
    "projects": SonarCloudEndpointConfig(
        name="projects",
        path="components/search_projects",
        data_key="components",
    ),
    "issues": SonarCloudEndpointConfig(
        name="issues",
        path="issues/search",
        data_key="issues",
        partition_key="creationDate",
    ),
    "metrics": SonarCloudEndpointConfig(
        name="metrics",
        path="metrics/search",
        data_key="metrics",
        requires_organization=False,
    ),
    "quality_gates": SonarCloudEndpointConfig(
        name="quality_gates",
        path="qualitygates/list",
        data_key="qualitygates",
        paginated=False,
    ),
}

ENDPOINTS = tuple(SONAR_CLOUD_ENDPOINTS.keys())

# No endpoint advertises a server-side timestamp filter we've verified, so none are incremental.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in SONAR_CLOUD_ENDPOINTS}
