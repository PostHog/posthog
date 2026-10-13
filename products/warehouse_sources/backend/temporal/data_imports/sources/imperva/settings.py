from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalFieldType

BASE_URL = "https://my.imperva.com"
SITES_BASE_URL = "https://api.imperva.com/sites-mgmt"
API_DOCS_URL = "https://docs-cybersec.thalesgroup.com/bundle/api-docs/page/api/api-overview.htm"
SITES_DOCS_URL = "https://docs-cybersec.thalesgroup.com/bundle/api-docs/page/website-management-api-definition.htm"
STATS_DOCS_URL = "https://docs-cybersec.thalesgroup.com/bundle/api-docs/page/traffic-stats-api-definition.htm"
DAY_MS = 86_400_000
HISTORY_DAYS = 90
ENDPOINTS = ("sites", "visits_timeseries", "hits_timeseries", "bandwidth_timeseries")
INCREMENTAL_FIELDS = {
    name: [incremental_field("timestamp", IncrementalFieldType.Integer)] for name in ENDPOINTS if name != "sites"
}
PRIMARY_KEYS = {name: ["account_id", "id", "timestamp"] for name in INCREMENTAL_FIELDS}
PRIMARY_KEYS["sites"] = ["id"]

AUTH_ERROR = "Imperva authentication failed. Check your API ID and API key."
PERMISSION_ERROR = "Imperva denied access. Check your account ID and API key permissions."
PLAN_ERROR = "Your Imperva plan does not include this feature. Check your subscription with Imperva."
