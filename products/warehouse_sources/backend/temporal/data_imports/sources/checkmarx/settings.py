from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@frozen
class RegionHosts:
    api_base_url: str
    iam_base_url: str


# Checkmarx One is deployed per region; both the API host and the IAM (auth) host vary with it.
# Region values match the documented multi-tenant deployments (https://checkmarx.com/resource/documents/en/34965-68630-checkmarx-one-regions.html).
CHECKMARX_REGION_HOSTS: dict[str, RegionHosts] = {
    "us": RegionHosts(api_base_url="https://ast.checkmarx.net", iam_base_url="https://iam.checkmarx.net"),
    "us2": RegionHosts(api_base_url="https://us.ast.checkmarx.net", iam_base_url="https://us.iam.checkmarx.net"),
    "eu": RegionHosts(api_base_url="https://eu.ast.checkmarx.net", iam_base_url="https://eu.iam.checkmarx.net"),
    "eu2": RegionHosts(api_base_url="https://eu-2.ast.checkmarx.net", iam_base_url="https://eu-2.iam.checkmarx.net"),
    "deu": RegionHosts(api_base_url="https://deu.ast.checkmarx.net", iam_base_url="https://deu.iam.checkmarx.net"),
    "anz": RegionHosts(api_base_url="https://anz.ast.checkmarx.net", iam_base_url="https://anz.iam.checkmarx.net"),
    "ind": RegionHosts(api_base_url="https://ind.ast.checkmarx.net", iam_base_url="https://ind.iam.checkmarx.net"),
    "sng": RegionHosts(api_base_url="https://sng.ast.checkmarx.net", iam_base_url="https://sng.iam.checkmarx.net"),
    "mea": RegionHosts(api_base_url="https://mea.ast.checkmarx.net", iam_base_url="https://mea.iam.checkmarx.net"),
}

_SCAN_CREATED_AT_INCREMENTAL_FIELD: IncrementalField = {
    "label": "scan_created_at",
    "type": IncrementalFieldType.DateTime,
    "field": "scan_created_at",
    "field_type": IncrementalFieldType.DateTime,
}


@dataclass
class CheckmarxEndpointConfig:
    name: str
    path: str
    # Key of the list of rows in the wrapped JSON response, e.g. {"projects": [...], "totalCount": n}.
    data_key: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable datetime field used for Delta partitioning (never an updated-at style field).
    partition_key: Optional[str] = None
    page_size: int = 100
    # Fan out over the scans list, requesting this endpoint once per scan id.
    fan_out_over_scans: bool = False
    # Query param that carries the scan id on fan-out requests.
    scan_id_param: Optional[str] = None
    # Safety overlap subtracted from the incremental watermark on every run. Fan-out endpoints key
    # their watermark on scan creation time, but a scan's results only exist once the scan finishes —
    # re-pulling a window of recent scans picks up results of scans that were still running (and
    # recent triage/state changes); merge dedupes the re-pulled rows on the primary key.
    incremental_lookback: Optional[timedelta] = None
    should_sync_default: bool = True


CHECKMARX_ENDPOINTS: dict[str, CheckmarxEndpointConfig] = {
    # Projects and applications have no server-side timestamp filter, so they are full refresh only.
    # Both are small (one row per project/application) so a full refresh per run is cheap.
    "projects": CheckmarxEndpointConfig(
        name="projects",
        path="/api/projects",
        data_key="projects",
        partition_key="createdAt",
    ),
    "applications": CheckmarxEndpointConfig(
        name="applications",
        path="/api/applications",
        data_key="applications",
        partition_key="createdAt",
    ),
    # The scans list accepts a `from-date` (ISO-8601) filter on scan creation time, which is the
    # server-side cursor for incremental sync.
    "scans": CheckmarxEndpointConfig(
        name="scans",
        path="/api/scans",
        data_key="scans",
        partition_key="createdAt",
        incremental_fields=[
            {
                "label": "createdAt",
                "type": IncrementalFieldType.DateTime,
                "field": "createdAt",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # Findings are keyed by scan, so incremental sync fetches scans created since the watermark and
    # pulls each scan's results. Rows carry injected `scan_id` / `scan_created_at` / `result_id`
    # columns (see checkmarx.py).
    "scan_results": CheckmarxEndpointConfig(
        name="scan_results",
        path="/api/results",
        data_key="results",
        primary_keys=["scan_id", "result_id"],
        partition_key="scan_created_at",
        incremental_fields=[_SCAN_CREATED_AT_INCREMENTAL_FIELD],
        fan_out_over_scans=True,
        scan_id_param="scan-id",
        incremental_lookback=timedelta(days=7),
    ),
    # Aggregated severity/status counters per scan, one row per scan.
    "scan_results_summary": CheckmarxEndpointConfig(
        name="scan_results_summary",
        path="/api/scan-summary",
        data_key="scansSummaries",
        primary_keys=["scan_id"],
        partition_key="scan_created_at",
        incremental_fields=[_SCAN_CREATED_AT_INCREMENTAL_FIELD],
        fan_out_over_scans=True,
        scan_id_param="scan-ids",
        incremental_lookback=timedelta(days=7),
    ),
}

ENDPOINTS = tuple(CHECKMARX_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CHECKMARX_ENDPOINTS.items()
}
