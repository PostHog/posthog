from products.notebooks.backend.temporal.data_v2 import (
    NotebookDataV2RunWorkflow,
    NotebookDataV2StartWorkflow,
    dispatch_data_v2_run_activity,
    mark_data_v2_run_failed_activity,
    provision_data_v2_kernel_activity,
)

WORKFLOWS = [
    NotebookDataV2StartWorkflow,
    NotebookDataV2RunWorkflow,
]

ACTIVITIES = [
    provision_data_v2_kernel_activity,
    dispatch_data_v2_run_activity,
    mark_data_v2_run_failed_activity,
]
