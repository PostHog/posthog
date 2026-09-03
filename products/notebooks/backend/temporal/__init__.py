from products.notebooks.backend.temporal.frame_materialize import (
    NotebookFrameMaterializeWorkflow,
    mark_frame_materialize_failed_activity,
    materialize_frame_activity,
)
from products.notebooks.backend.temporal.sql_v2 import (
    NotebookSQLV2RunWorkflow,
    dispatch_sql_v2_run_activity,
    expire_sql_v2_run_activity,
    mark_sql_v2_run_failed_activity,
)
from products.notebooks.backend.temporal.widget_generation import (
    NotebookWidgetGenerationWorkflow,
    generate_widget_activity,
    mark_widget_generation_capacity_failed_activity,
    mark_widget_generation_failed_activity,
)

WORKFLOWS = [
    NotebookSQLV2RunWorkflow,
    NotebookFrameMaterializeWorkflow,
    NotebookWidgetGenerationWorkflow,
]

ACTIVITIES = [
    dispatch_sql_v2_run_activity,
    expire_sql_v2_run_activity,
    mark_sql_v2_run_failed_activity,
    materialize_frame_activity,
    mark_frame_materialize_failed_activity,
    generate_widget_activity,
    mark_widget_generation_failed_activity,
    mark_widget_generation_capacity_failed_activity,
]
