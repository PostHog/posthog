from typing import cast

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint

BASE_URL = "https://api.gologin.com"
REQUEST_TIMEOUT = (10.0, 60.0)

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

AUTH_ERROR = "GoLogin rejected the API key. Check the key in Settings > API."
PERMISSION_ERROR = "GoLogin denied access. Check the API key and your account permissions."
