from dataclasses import field
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import PartitionFormat
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@frozen
class CloudinaryEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    # Key the rows sit under in the response envelope. None when the whole body is one row.
    data_key: Optional[str] = None
    params: dict[str, Any] = field(default_factory=dict)
    partition_key: Optional[str] = None
    partition_format: PartitionFormat = "week"


# Cloudinary caps a page at 500 rows and counts every call against an hourly quota, so ask for the
# largest page it allows.
MAX_RESULTS = 500

CLOUDINARY_ENDPOINTS: dict[str, CloudinaryEndpointConfig] = {
    "images": CloudinaryEndpointConfig(
        name="images",
        path="/resources/image",
        data_key="resources",
        primary_keys=["asset_id"],
        params={"max_results": MAX_RESULTS, "context": "true", "tags": "true"},
        partition_key="created_at",
    ),
    "videos": CloudinaryEndpointConfig(
        name="videos",
        path="/resources/video",
        data_key="resources",
        primary_keys=["asset_id"],
        params={"max_results": MAX_RESULTS, "context": "true", "tags": "true"},
        partition_key="created_at",
    ),
    "raw_files": CloudinaryEndpointConfig(
        name="raw_files",
        path="/resources/raw",
        data_key="resources",
        primary_keys=["asset_id"],
        params={"max_results": MAX_RESULTS, "context": "true", "tags": "true"},
        partition_key="created_at",
    ),
    "folders": CloudinaryEndpointConfig(
        name="folders",
        path="/folders",
        data_key="folders",
        primary_keys=["path"],
        params={"max_results": MAX_RESULTS},
    ),
    "transformations": CloudinaryEndpointConfig(
        name="transformations",
        path="/transformations",
        data_key="transformations",
        primary_keys=["name"],
        params={"max_results": MAX_RESULTS},
    ),
    "upload_presets": CloudinaryEndpointConfig(
        name="upload_presets",
        path="/upload_presets",
        data_key="presets",
        primary_keys=["name"],
        params={"max_results": MAX_RESULTS},
    ),
    "subfolders": CloudinaryEndpointConfig(
        name="subfolders",
        path="/folders/{folder}",
        data_key="folders",
        primary_keys=["path"],
        params={"max_results": MAX_RESULTS},
    ),
    "last_access_report_resources": CloudinaryEndpointConfig(
        name="last_access_report_resources",
        path="/resources/last_access_report/{report_id}",
        data_key="resources",
        primary_keys=["report_id", "asset_id"],
        params={"max_results": MAX_RESULTS},
        partition_key="created_at",
    ),
    "usage": CloudinaryEndpointConfig(
        name="usage",
        path="/usage/{date}",
        primary_keys=["date"],
        partition_key="date",
        partition_format="month",
    ),
}

ENDPOINTS = tuple(CLOUDINARY_ENDPOINTS.keys())

LAST_ACCESS_REPORTS_PATH = "/resources_last_access_reports"

# The usage endpoint only answers for dates in the last 3 months, and the shortest 3-month span is 89 days.
USAGE_HISTORY_DAYS = 89
# Cloudinary refreshes usage figures periodically, so an incremental sync re-reads the last few days.
USAGE_RESTATEMENT_DAYS = 2

# Cloudinary's only time filter on the asset lists is `start_at`, which selects on update time while
# the list itself is ordered by creation time. A watermark built on it would skip rows, so the list
# tables are a full refresh until that ordering can be verified against a live account. Usage is
# requested one date at a time, so its date is a real server-side filter.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "usage": [
        {
            "label": "date",
            "type": IncrementalFieldType.Date,
            "field": "date",
            "field_type": IncrementalFieldType.Date,
        }
    ],
}
