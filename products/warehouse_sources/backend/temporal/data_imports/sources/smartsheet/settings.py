from dataclasses import dataclass
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Smartsheet's account-level list endpoints share the same page-based envelope
# ({pageNumber, pageSize, totalPages, totalCount, data: [...]}). We model each as a top-level
# resource and full-refresh it on every sync.
#
# The report child endpoints (report_columns / report_scope) are different: they fan out from
# each report and page by token (`lastKey` / `maxItems`) rather than page number — see smartsheet.py.
#
# The metadata endpoints are full refresh. Although `List Sheets` / `List Reports` document a
# `modifiedSince` server-side filter, these list endpoints expose no stable `sort` parameter, so we
# cannot guarantee the ascending ordering the pipeline relies on to advance an incremental watermark
# safely across resumed syncs. The payloads are small (account-level metadata and per-report
# structure), so a full refresh is cheap and correct.
#
# `sheet_rows` (`rowsModifiedSince`) and `events` (`since`) are the exceptions: their data is large
# and the server filters it. Neither returns rows in watermark order, so both report
# sort_mode="desc", which commits the watermark only when the sync completes.

# The report child endpoints page by token; `maxItems` default and minimum is 100. The `reports`
# parent walk keeps the same 100-row page size the top-level `reports` endpoint uses.
PAGE_SIZE = 100
# Get Sheet pages its rows with the same `page` / `pageSize` params. A row carries one cell per
# column, so rows get a larger page than the metadata lists but stay well below the response cap.
ROWS_PAGE_SIZE = 500
# The documented maximum of `maxCount` on List Events.
EVENTS_MAX_COUNT = 10000

# How an endpoint pages: `page_number` stops on `totalPages`, `token` follows `lastKey`,
# `sheet_rows` stops on the sheet's `totalRowCount`, and `event_stream` follows
# `nextStreamPosition` until `moreAvailable` is false.
Pagination = Literal["page_number", "token", "single_page", "sheet_rows", "event_stream"]


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
    # `default_incremental_field` and `page_size` also satisfy the shared dependent-resource
    # builder's endpoint protocol.
    default_incremental_field: Optional[str] = None
    page_size: int = PAGE_SIZE
    fanout: Optional[DependentEndpointConfig] = None
    pagination: Pagination = "page_number"
    data_selector: str = "data"
    sort_mode: SortMode | None = None


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

# Sheet ids and group ids are injected into each child row the same way as the report id above.
_SHEET_PARENT_FANOUT = DependentEndpointConfig(
    parent_name="sheets",
    resolve_param="sheet_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "sheetId"},
    parent_params={"pageSize": PAGE_SIZE},
)

_GROUP_PARENT_FANOUT = DependentEndpointConfig(
    parent_name="groups",
    resolve_param="group_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "groupId"},
    parent_params={"pageSize": PAGE_SIZE},
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
        pagination="token",
    ),
    "report_scope": SmartsheetEndpointConfig(
        name="report_scope",
        path="/reports/{report_id}/scope",
        incremental_fields=[],
        # A scope row is one source sheet or workspace of a report; assetId is unique only within
        # its assetType, so the key spans the report id, the asset type, and the asset id.
        primary_key=["reportId", "assetType", "assetId"],
        fanout=_REPORT_PARENT_FANOUT,
        pagination="token",
    ),
    "sheet_rows": SmartsheetEndpointConfig(
        name="sheet_rows",
        path="/sheets/{sheet_id}",
        incremental_fields=[
            {
                "label": "modifiedAt",
                "type": IncrementalFieldType.DateTime,
                "field": "modifiedAt",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        default_incremental_field="modifiedAt",
        # Row ids are only documented as unique within a sheet, so the sheet id leads the key.
        primary_key=["sheetId", "id"],
        page_size=ROWS_PAGE_SIZE,
        fanout=_SHEET_PARENT_FANOUT,
        pagination="sheet_rows",
        data_selector="rows",
        sort_mode="desc",
    ),
    "sheet_columns": SmartsheetEndpointConfig(
        name="sheet_columns",
        path="/sheets/{sheet_id}/columns",
        incremental_fields=[],
        primary_key=["sheetId", "id"],
        fanout=_SHEET_PARENT_FANOUT,
    ),
    "events": SmartsheetEndpointConfig(
        name="events",
        path="/events",
        incremental_fields=[
            {
                "label": "eventTimestamp",
                "type": IncrementalFieldType.DateTime,
                "field": "eventTimestamp",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        default_incremental_field="eventTimestamp",
        primary_key="eventId",
        partition_key="eventTimestamp",
        page_size=EVENTS_MAX_COUNT,
        pagination="event_stream",
        sort_mode="desc",
    ),
    "groups": SmartsheetEndpointConfig(
        name="groups",
        path="/groups",
        partition_key="createdAt",
        incremental_fields=[],
    ),
    "group_members": SmartsheetEndpointConfig(
        name="group_members",
        path="/groups/{group_id}",
        incremental_fields=[],
        # A member id is a user id, so it repeats across every group the user belongs to.
        primary_key=["groupId", "id"],
        fanout=_GROUP_PARENT_FANOUT,
        pagination="single_page",
        data_selector="members",
    ),
}

ENDPOINTS = tuple(SMARTSHEET_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SMARTSHEET_ENDPOINTS.items()
}
