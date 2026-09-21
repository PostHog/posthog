from dataclasses import field
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


@frozen
class CheckmarxFanOutConfig:
    # Endpoint whose rows are the parents: the child endpoint is requested once per parent row.
    parent: str
    # Columns every child row is stamped with, carrying the parent's id and creation time.
    parent_id_field: str
    parent_created_at_field: str
    # Query param that carries the parent id. None means the id fills the `{parent_id}`
    # placeholder in the child endpoint's path instead.
    id_param: Optional[str] = None


@frozen
class CheckmarxEndpointConfig:
    name: str
    path: str
    # Key of the list of rows in the wrapped JSON response, e.g. {"projects": [...], "totalCount": n}.
    # None when the endpoint returns a bare JSON array.
    data_key: Optional[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable datetime field used for Delta partitioning (never an updated-at style field).
    partition_key: Optional[str] = None
    page_size: int = 100
    # Query params sent on every request to this endpoint.
    params: dict[str, str] = field(default_factory=dict)
    # False for endpoints that return their whole collection in one response.
    paginated: bool = True
    # Set when the endpoint returns an array of bare strings: each one becomes a row under this column.
    scalar_row_field: Optional[str] = None
    # Query param carrying the incremental watermark, on the endpoints that accept one.
    from_date_param: Optional[str] = None
    # Set to request this endpoint once per row of a parent endpoint.
    fan_out: Optional[CheckmarxFanOutConfig] = None
    # Safety overlap subtracted from the incremental watermark on every run. Fan-out endpoints key
    # their watermark on scan creation time, but a scan's results only exist once the scan finishes —
    # re-pulling a window of recent scans picks up results of scans that were still running (and
    # recent triage/state changes); merge dedupes the re-pulled rows on the primary key.
    incremental_lookback: Optional[timedelta] = None
    should_sync_default: bool = True


def _scans_fan_out(id_param: str) -> CheckmarxFanOutConfig:
    return CheckmarxFanOutConfig(
        parent="scans",
        parent_id_field="scan_id",
        parent_created_at_field="scan_created_at",
        id_param=id_param,
    )


def _scalar_list(name: str, path: str) -> CheckmarxEndpointConfig:
    return CheckmarxEndpointConfig(
        name=name,
        path=path,
        data_key=None,
        paginated=False,
        scalar_row_field="value",
        primary_keys=["value"],
    )


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
        from_date_param="from-date",
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
        fan_out=_scans_fan_out("scan-id"),
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
        fan_out=_scans_fan_out("scan-ids"),
        incremental_lookback=timedelta(days=7),
    ),
    # One row per rule assigning projects to an application. The applications list already carries
    # these nested under `rules`; a flat table joins to `applications` without unnesting.
    "application_rules": CheckmarxEndpointConfig(
        name="application_rules",
        path="/api/applications/{parent_id}/project-rules",
        data_key=None,
        paginated=False,
        primary_keys=["application_id", "id"],
        partition_key="application_created_at",
        fan_out=CheckmarxFanOutConfig(
            parent="applications",
            parent_id_field="application_id",
            parent_created_at_field="application_created_at",
        ),
    ),
    # Triage history: every state, severity and comment change made to a project's findings, with
    # the user, timestamp and origin. Keyed on the project rather than the finding — the
    # per-similarity-id route would need one request per finding.
    "sast_predicates_changelog": CheckmarxEndpointConfig(
        name="sast_predicates_changelog",
        path="/api/sast-results-predicates/changelog",
        data_key="results",
        params={"entityType": "projectID", "history": "true"},
        primary_keys=["project_id", "change_id"],
        partition_key="project_created_at",
        fan_out=CheckmarxFanOutConfig(
            parent="projects",
            parent_id_field="project_id",
            parent_created_at_field="project_created_at",
            id_param="entityId",
        ),
    ),
    # The Lists API returns each enum as a bare array of strings, so every value becomes a row
    # under a single `value` column. These decode the state, status and severity columns on
    # scan_results, and are the full set of values a result can carry.
    "result_states": _scalar_list("result_states", "/api/lists/states"),
    "result_statuses": _scalar_list("result_statuses", "/api/lists/statuses"),
    "result_severities": _scalar_list("result_severities", "/api/lists/severities"),
    # Triage states defined by the tenant, on top of the built-in ones in `result_states`. Deleted
    # states are requested too, so a finding left in a since-removed state still resolves to a name.
    "custom_states": CheckmarxEndpointConfig(
        name="custom_states",
        path="/api/custom-states",
        data_key=None,
        paginated=False,
        params={"include-deleted": "true"},
    ),
}

ENDPOINTS = tuple(CHECKMARX_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CHECKMARX_ENDPOINTS.items()
}
