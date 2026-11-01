from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.types import IncrementalField

# InsightVM's Insight Platform Cloud API is deployed per data-residency region. A single API key
# belongs to one region, so the host is chosen by the `region` form field rather than a
# user-supplied URL — the set is fixed, so there is no SSRF surface.
REGION_HOSTS: dict[str, str] = {
    "us": "https://us.api.insight.rapid7.com",
    "eu": "https://eu.api.insight.rapid7.com",
    "ca": "https://ca.api.insight.rapid7.com",
    "au": "https://au.api.insight.rapid7.com",
    "ap": "https://ap.api.insight.rapid7.com",
    "jp": "https://jp.api.insight.rapid7.com",
}

# The Cloud Integrations API (v4) exposes purpose-built bulk-export search endpoints. They are
# POST search operations that page with a `size` query param (max 1000) and a `cursor` token
# returned in the response metadata.
API_BASE_PATH = "/vm/v4/integration"
MAX_PAGE_SIZE = 1000

# The plain GET collections (scans, scan engines) page with zero-based `page` + `size` and no cursor.
# The API caps those at 500 rows per page and 10,000 results per walk, so the walk stops at the
# last page inside that window instead of requesting one the API refuses.
PAGE_NUMBER_PAGE_SIZE = 500
PAGE_NUMBER_MAX_PAGE = 10_000 // PAGE_NUMBER_PAGE_SIZE - 1


@dataclass
class Rapid7InsightvmEndpointConfig:
    name: str
    # Path segment appended to `{host}{API_BASE_PATH}/` (e.g. "assets").
    path: str
    primary_keys: list[str]
    # Search endpoints are POST + cursor; plain collection endpoints are GET + page number.
    method: Literal["GET", "POST"] = "POST"
    pagination: Literal["cursor", "page_number"] = "cursor"
    params: dict[str, str] = field(default_factory=dict)
    # Incremental sync is only advertised where the API exposes a confirmed server-side timestamp
    # filter. The v4 search body accepts filter expressions but their timestamp-filter fidelity is
    # unverified and the GET collections have no time filter, so every endpoint ships full refresh.
    supports_incremental: bool = False
    supports_append: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Must be a STABLE datetime field (never `updated_at`/`last_seen`) so partitions don't rewrite
    # every sync. Left unset: the v4 objects have no field confirmed stable across scans, so we
    # don't partition rather than partition on a field that might be revised.
    partition_key: str | None = None


RAPID7_INSIGHTVM_ENDPOINTS: dict[str, Rapid7InsightvmEndpointConfig] = {
    # Asset inventory with embedded vulnerability findings and solutions. Purpose-built for bulk
    # export — the whole host record comes back in one response.
    "assets": Rapid7InsightvmEndpointConfig(
        name="assets",
        path="assets",
        primary_keys=["id"],
    ),
    # Unique vulnerability definitions with CVE mappings, CVSS scores, severity, and references.
    "vulnerabilities": Rapid7InsightvmEndpointConfig(
        name="vulnerabilities",
        path="vulnerabilities",
        primary_keys=["id"],
    ),
    # Sites have no id in the v4 API; a site name is unique and is how assets reference their site.
    "sites": Rapid7InsightvmEndpointConfig(
        name="sites",
        path="sites",
        primary_keys=["name"],
    ),
    "scans": Rapid7InsightvmEndpointConfig(
        name="scans",
        path="scan",
        primary_keys=["id"],
        method="GET",
        pagination="page_number",
        params={"includeDetails": "true"},
    ),
    "scan_engines": Rapid7InsightvmEndpointConfig(
        name="scan_engines",
        path="scan/engine",
        primary_keys=["id"],
        method="GET",
        pagination="page_number",
    ),
}

ENDPOINTS = tuple(RAPID7_INSIGHTVM_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in RAPID7_INSIGHTVM_ENDPOINTS.items()
}
