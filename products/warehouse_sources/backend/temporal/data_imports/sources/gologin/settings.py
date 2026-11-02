from typing import cast

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

BASE_URL = "https://api.gologin.com"
REQUEST_TIMEOUT = (10.0, 60.0)

# The workspace usage endpoint accepts a trailing window of 1 to 30 days.
CLOUD_USAGE_MAX_DAYS = 30

ENDPOINTS = cast(
    dict[str, Endpoint],
    {
        # PageNumberPaginator accepts base_page, but its config TypedDict does not expose that constructor argument.
        "profiles": {
            "path": "/browser/v2",
            "data_selector": "profiles",
            "data_selector_required": True,
            "params": {"sorterField": "createdAt", "sorterOrder": "ascend"},
            "paginator": {"type": "page_number", "base_page": 1, "total_path": None},
        },
        "workspaces": {
            "path": "/workspaces",
            "data_selector": "$",
            "data_selector_required": True,
            "paginator": "single_page",
        },
        "proxy_devices": {
            "path": "/proxy-devices",
            "data_selector": "devices",
            "data_selector_required": True,
            "paginator": "single_page",
        },
    },
)

# Tags, folders, deleted profiles and cloud usage are scoped to one workspace per request,
# so these endpoints fan out over `workspaces` and bind its id into `{workspace_id}`.
WORKSPACE_ENDPOINTS = cast(
    dict[str, Endpoint],
    {
        "tags": {
            "path": "/tags/all?workspace={workspace_id}",
            "data_selector": "tags",
            "data_selector_required": True,
            "paginator": "single_page",
        },
        # GET /folders is the legacy per-user listing with no response schema; the workspace
        # read documents its folders and covers every workspace.
        "folders": {
            "path": "/workspaces/{workspace_id}",
            "data_selector": "folders",
            "data_selector_required": True,
            "paginator": "single_page",
        },
        "deleted_profiles": {
            "path": "/deleted-profiles/v2?currentWorkspace={workspace_id}",
            "data_selector": "deletedProfilesList",
            "data_selector_required": True,
        },
        "cloud_usage_daily": {
            "path": "/cloud-usage/stats?workspaceId={workspace_id}",
            "data_selector": "days",
            "data_selector_required": True,
            "paginator": "single_page",
        },
    },
)

PRIMARY_KEYS: dict[str, list[str]] = {
    "tags": ["workspace_id", "id"],
    "folders": ["workspace_id", "id"],
    "deleted_profiles": ["workspace_id", "profileId"],
    "cloud_usage_daily": ["workspace_id", "date"],
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    # GoLogin purges deleted profiles after 120 hours and has no time filter, so each run reads the
    # whole short list. Merging keeps deletions after GoLogin purges them.
    "deleted_profiles": [
        {
            "label": "deletedAt",
            "type": IncrementalFieldType.DateTime,
            "field": "deletedAt",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "cloud_usage_daily": [
        {
            "label": "date",
            "type": IncrementalFieldType.Date,
            "field": "date",
            "field_type": IncrementalFieldType.Date,
        }
    ],
}

AUTH_ERROR = "GoLogin rejected the API key. Check the key in Settings > API."
PERMISSION_ERROR = "GoLogin denied access. Check the API key and your account permissions."
