from products.notebooks.backend.temporal.sql_v2 import (
    NotebookSQLV2RunWorkflow,
    dispatch_sql_v2_run_activity,
    mark_sql_v2_run_failed_activity,
)

WORKFLOWS = [
    NotebookSQLV2RunWorkflow,
]

ACTIVITIES = [
    dispatch_sql_v2_run_activity,
    mark_sql_v2_run_failed_activity,
]
