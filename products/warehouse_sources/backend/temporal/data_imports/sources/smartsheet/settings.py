from dataclasses import dataclass
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# Smartsheet's account-level list endpoints share the same page-based envelope
# ({pageNumber, pageSize, totalPages, totalCount, data: [...]}). We model each as a top-level
# resource and full-refresh it on every sync.
#
# The report child endpoints (report_columns / report_scope) are different: they fan out from
# each report and page by token (`lastKey` / `maxItems`) rather than page number — see smartsheet.py.
#
# Incremental sync is intentionally not enabled anywhere. Although `List Sheets` / `List Reports`
# document a `modifiedSince` server-side filter, these list endpoints expose no stable `sort`
# parameter, so we cannot guarantee the ascending ordering the pipeline relies on to advance an
# incremental watermark safely across resumed syncs. The report child endpoints expose no
# timestamp filter at all. The payloads here are small (account-level metadata and per-report
# structure), so a full refresh is cheap and correct.

# The report child endpoints page by token; `maxItems` default and minimum is 100. The `reports`
# parent walk keeps the same 100-row page size the top-level `reports` endpoint uses.
PAGE_SIZE = 100


# Mutable so instances satisfy the shared FanoutEndpointLike protocol, which declares settable
# attributes; a frozen dataclass would fail that structural check.
@dataclass(frozen=False)
class SmartsheetEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    primary_key: str | list[str] = "id"
    # A stable creation-date field used for datetime partitioning. Only set it where the
    # list response is documented to return it on every row.
    partition_key: Optional[str] = None
    # Fan-out plumbing for the report child endpoints. `default_incremental_field` and
    # `page_size` satisfy the shared dependent-resource builder's endpoint protocol; both stay
    # at their defaults because these endpoints are full refresh.
    default_incremental_field: Optional[str] = None
    page_size: int = PAGE_SIZE
    fanout: Optional[DependentEndpointConfig] = None


# The parent-report id injected into each report child row (via include_from_parent), used as the
# leading component of the child's composite key. Report-scoped ids repeat across reports, so the
# report id is what makes each key unique table-wide.
_REPORT_PARENT_FANOUT = DependentEndpointConfig(
    parent_name="reports",
    resolve_param="report_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "reportId"},
    parent_params={"pageSize": PAGE_SIZE},
    child_params={"maxItems": PAGE_SIZE},
)


SMARTSHEET_ENDPOINTS: dict[str, SmartsheetEndpointConfig] = {
    "sheets": SmartsheetEndpointConfig(
        name="sheets",
        path="/sheets",
        partition_key="createdAt",
        incremental_fields=[],
    ),
    "reports": SmartsheetEndpointConfig(
        name="reports",
        path="/reports",
        partition_key="createdAt",
        incremental_fields=[],
    ),
    "workspaces": SmartsheetEndpointConfig(
        name="workspaces",
        path="/workspaces",
        incremental_fields=[],
    ),
    "users": SmartsheetEndpointConfig(
        name="users",
        path="/users",
        incremental_fields=[],
    ),
    "contacts": SmartsheetEndpointConfig(
        name="contacts",
        path="/contacts",
        incremental_fields=[],
    ),
    "templates": SmartsheetEndpointConfig(
        name="templates",
        path="/templates",
        incremental_fields=[],
    ),
    "report_columns": SmartsheetEndpointConfig(
        name="report_columns",
        path="/reports/{report_id}/columns",
        incremental_fields=[],
        # `virtualId` addresses a report column (GET /reports/{reportId}/columns/{columnVirtualId})
        # but is unique only within its report, so the parent report id leads the key.
        primary_key=["reportId", "virtualId"],
        fanout=_REPORT_PARENT_FANOUT,
    ),
    "report_scope": SmartsheetEndpointConfig(
        name="report_scope",
        path="/reports/{report_id}/scope",
        incremental_fields=[],
        # A scope row is one source sheet or workspace of a report; assetId is unique only within
        # its assetType, so the key spans the report id, the asset type, and the asset id.
        primary_key=["reportId", "assetType", "assetId"],
        fanout=_REPORT_PARENT_FANOUT,
    ),
}

ENDPOINTS = tuple(SMARTSHEET_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SMARTSHEET_ENDPOINTS.items()
}
