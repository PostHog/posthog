from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint

REGIONS = {
    "EU": "https://api.frontegg.com",
    "US": "https://api.us.frontegg.com",
    "CA": "https://api.ca.frontegg.com",
    "AU": "https://api.au.frontegg.com",
}

ENDPOINTS: dict[str, Endpoint] = {
    "users": {
        "path": "identity/resources/users/{api_version}",
        "data_selector": "items",
        "params": {"_limit": 200, "_sortBy": "createdAt", "_order": "ASC"},
        "paginator": {"type": "page_number", "page_param": "_offset", "total_path": "_metadata.totalPages"},
    },
    "roles": {
        "path": "identity/resources/roles/v2",
        "data_selector": "items",
        "params": {"_limit": 200, "_sortBy": "createdAt", "_order": "ASC"},
        "paginator": {"type": "page_number", "page_param": "_offset", "total_path": "_metadata.totalPages"},
    },
    "permissions": {
        "path": "identity/resources/permissions/v1",
        "data_selector": "$",
        "paginator": "single_page",
    },
}

AUTH_ERROR = "Frontegg authentication failed. Check your client ID, API key, and region."
PERMISSION_ERROR = "Frontegg denied access. Check the permissions for your environment API key."
REGION_ERROR = "Select a supported Frontegg region: EU, US, CA, or AU."
