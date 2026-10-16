from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

ENDPOINTS = {
    "executions": "executions/search",
    "flows": "flows/search",
    "triggers": "triggers/search",
    "task_runs": "executions/{executionId}",
    "execution_metrics": "metrics/{executionId}",
    "flow_revisions": "flows/{namespace}/{id}/revisions",
    "logs": "logs/search",
}
# Child tables read one parent row at a time, so a credential probe reads the parent list instead.
FANOUT_PARENTS = {
    "task_runs": "executions",
    "execution_metrics": "executions",
    "flow_revisions": "flows",
}
PRIMARY_KEYS = {
    "executions": ["id"],
    "flows": ["namespace", "id"],
    "triggers": ["namespace", "flow_id", "trigger_id"],
    "task_runs": ["executionId", "id"],
    "execution_metrics": ["entry_id"],
    "flow_revisions": ["namespace", "id", "revision"],
    "logs": ["entry_id"],
}
INCREMENTAL_FIELDS = {
    "executions": [incremental_field("start_date")],
    "task_runs": [incremental_field("execution_start_date")],
    "execution_metrics": [incremental_field("execution_start_date")],
    "logs": [incremental_field("timestamp")],
}
PAGE_SIZE = 100
# Kestra's maximum page size. Log and metric pages are small rows read in bulk.
LARGE_PAGE_SIZE = 1000
EXECUTION_LOOKBACK_SECONDS = 7 * 24 * 60 * 60
# Workers write logs asynchronously, so a log can arrive after a later log was already synced.
LOG_LOOKBACK_SECONDS = 60 * 60
LOOKBACK_SECONDS = {
    "executions": EXECUTION_LOOKBACK_SECONDS,
    "task_runs": EXECUTION_LOOKBACK_SECONDS,
    "execution_metrics": EXECUTION_LOOKBACK_SECONDS,
    "logs": LOG_LOOKBACK_SECONDS,
}
AUTH_ERROR = "Kestra rejected your credentials. Check your API token or Basic authentication details."
PERMISSION_ERROR = "Kestra denied access. Grant read permission for this table in the selected tenant."
