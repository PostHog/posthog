from datetime import timedelta

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

API_BASE_URL = "https://api.applicationinsights.io"
API_DOCS_URL = "https://learn.microsoft.com/en-us/rest/api/application-insights/query/execute"
AUTH_DOCS_URL = "https://learn.microsoft.com/en-us/azure/azure-monitor/app/azure-ad-authentication"
PAGE_SIZE = 1000
SYNC_WINDOW = timedelta(days=7)
LATE_ARRIVAL_OVERLAP = timedelta(hours=1)
ENDPOINTS = ("requests", "dependencies", "exceptions", "availabilityResults")
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "label": "timestamp",
            "field": "timestamp",
            "type": IncrementalFieldType.DateTime,
            "field_type": IncrementalFieldType.DateTime,
        }
    ]
    for name in ENDPOINTS
}
