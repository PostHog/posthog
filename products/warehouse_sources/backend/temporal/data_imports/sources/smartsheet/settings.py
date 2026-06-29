from dataclasses import dataclass
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField

# Smartsheet's list endpoints all share the same offset-based pagination envelope
# ({pageNumber, pageSize, totalPages, totalCount, data: [...]}). We model each as a
# top-level resource and full-refresh it on every sync.
#
# Incremental sync is intentionally not enabled. Although `List Sheets` / `List Reports`
# document a `modifiedSince` server-side filter, these list endpoints expose no stable
# `sort` parameter, so we cannot guarantee the ascending ordering the pipeline relies on
# to advance an incremental watermark safely across resumed syncs. The payloads here are
# small (account-level metadata listings), so a full refresh is cheap and correct.


@dataclass
class SmartsheetEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    primary_key: str = "id"
    # A stable creation-date field used for datetime partitioning. Only set it where the
    # list response is documented to return it on every row.
    partition_key: Optional[str] = None


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
}

ENDPOINTS = tuple(SMARTSHEET_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SMARTSHEET_ENDPOINTS.items()
}
