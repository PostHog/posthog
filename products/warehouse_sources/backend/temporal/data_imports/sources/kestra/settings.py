from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

ENDPOINTS = {
    "executions": "executions/search",
    "flows": "flows/search",
    "triggers": "triggers/search",
}
PRIMARY_KEYS = {
    "executions": ["id"],
    "flows": ["namespace", "id"],
    "triggers": ["namespace", "flow_id", "trigger_id"],
}
INCREMENTAL_FIELDS = {"executions": [incremental_field("start_date")]}
PAGE_SIZE = 100
EXECUTION_LOOKBACK_SECONDS = 7 * 24 * 60 * 60
AUTH_ERROR = "Kestra rejected your credentials. Check your API token or Basic authentication details."
PERMISSION_ERROR = "Kestra denied access. Grant read permission for this table in the selected tenant."
