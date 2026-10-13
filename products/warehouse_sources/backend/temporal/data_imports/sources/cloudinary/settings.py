from dataclasses import field
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField


@frozen
class CloudinaryEndpointConfig:
    name: str
    path: str
    # Key the rows sit under in the response envelope.
    data_key: str
    primary_key: str
    params: dict[str, Any] = field(default_factory=dict)
    partition_key: Optional[str] = None


# Cloudinary caps a page at 500 rows and counts every call against an hourly quota, so ask for the
# largest page it allows.
MAX_RESULTS = 500

CLOUDINARY_ENDPOINTS: dict[str, CloudinaryEndpointConfig] = {
    "images": CloudinaryEndpointConfig(
        name="images",
        path="/resources/image",
        data_key="resources",
        primary_key="asset_id",
        params={"max_results": MAX_RESULTS, "context": "true", "tags": "true"},
        partition_key="created_at",
    ),
    "videos": CloudinaryEndpointConfig(
        name="videos",
        path="/resources/video",
        data_key="resources",
        primary_key="asset_id",
        params={"max_results": MAX_RESULTS, "context": "true", "tags": "true"},
        partition_key="created_at",
    ),
    "raw_files": CloudinaryEndpointConfig(
        name="raw_files",
        path="/resources/raw",
        data_key="resources",
        primary_key="asset_id",
        params={"max_results": MAX_RESULTS, "context": "true", "tags": "true"},
        partition_key="created_at",
    ),
    "folders": CloudinaryEndpointConfig(
        name="folders",
        path="/folders",
        data_key="folders",
        primary_key="path",
        params={"max_results": MAX_RESULTS},
    ),
    "transformations": CloudinaryEndpointConfig(
        name="transformations",
        path="/transformations",
        data_key="transformations",
        primary_key="name",
        params={"max_results": MAX_RESULTS},
    ),
    "upload_presets": CloudinaryEndpointConfig(
        name="upload_presets",
        path="/upload_presets",
        data_key="presets",
        primary_key="name",
        params={"max_results": MAX_RESULTS},
    ),
}

ENDPOINTS = tuple(CLOUDINARY_ENDPOINTS.keys())

# Cloudinary's only time filter on the asset lists is `start_at`, which selects on update time while
# the list itself is ordered by creation time. A watermark built on it would skip rows, so every
# table is a full refresh until that ordering can be verified against a live account.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
