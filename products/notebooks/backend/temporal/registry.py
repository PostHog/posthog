"""The workflow and activity lists the worker bootstrap registers.

These live here rather than in `__init__.py` so that importing any single workflow
module does not pull in all of them. The whole-notebook run workflow imports the run
logic, which reaches back down to the cell dispatch, which starts a workflow of its own —
an eager package `__init__` turned that chain into an import cycle.
"""

from products.notebooks.backend.temporal.frame_materialize import (
    NotebookFrameMaterializeWorkflow,
    mark_frame_materialize_failed_activity,
    materialize_frame_activity,
)
from products.notebooks.backend.temporal.notebook_run import (
    NotebookRunWorkflow,
    check_notebook_cell_activity,
    dispatch_notebook_cell_activity,
    finish_notebook_run_activity,
    read_notebook_run_status_activity,
    stop_notebook_cell_activity,
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
    NotebookRunWorkflow,
    NotebookSQLV2RunWorkflow,
    NotebookFrameMaterializeWorkflow,
    NotebookWidgetGenerationWorkflow,
]

ACTIVITIES = [
    check_notebook_cell_activity,
    dispatch_notebook_cell_activity,
    finish_notebook_run_activity,
    read_notebook_run_status_activity,
    stop_notebook_cell_activity,
    dispatch_sql_v2_run_activity,
    expire_sql_v2_run_activity,
    mark_sql_v2_run_failed_activity,
    materialize_frame_activity,
    mark_frame_materialize_failed_activity,
    generate_widget_activity,
    mark_widget_generation_failed_activity,
    mark_widget_generation_capacity_failed_activity,
]
