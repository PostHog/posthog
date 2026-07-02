from products.notebooks.backend.temporal.data_v2 import (
    NotebookDataV2RunWorkflow,
    dispatch_data_v2_run_activity,
    mark_data_v2_run_failed_activity,
)

WORKFLOWS = [
    NotebookDataV2RunWorkflow,
]

ACTIVITIES = [
    dispatch_data_v2_run_activity,
    mark_data_v2_run_failed_activity,
]
