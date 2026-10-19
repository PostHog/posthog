from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

API_BASE_URL = "https://www.ncei.noaa.gov/cdo-web/api"
API_DOCS_URL = "https://www.ncei.noaa.gov/cdo-web/webservices/v2"
PAGE_SIZE = 1000
ENDPOINTS = ("data", "datasets", "stations", "datatypes", "datacategories", "locations", "locationcategories")
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "data": [
        {
            "label": "date",
            "field": "date",
            "type": IncrementalFieldType.DateTime,
            "field_type": IncrementalFieldType.DateTime,
        }
    ]
}
AUTH_ERROR = "NOAA authentication failed. Check your API token."
REQUEST_ERROR = "NOAA rejected the request. Check your dataset ID, station ID, and start date."
RESPONSE_ACTIONS: list[ResponseAction] = [
    {"status_code": 400, "content": "Token parameter is required.", "action": "raise", "message": AUTH_ERROR},
    {
        "status_code": 400,
        "content": "The token parameter provided is not valid.",
        "action": "raise",
        "message": AUTH_ERROR,
    },
    {"status_code": 401, "action": "raise", "message": AUTH_ERROR},
    {"status_code": 403, "action": "raise", "message": AUTH_ERROR},
    {"status_code": 400, "action": "raise", "message": REQUEST_ERROR},
]
