"""
Facade re-exports for the tasks Temporal surface.

Wiring that core registers and dispatches on, as objects: the worker registers
``WORKFLOWS``/``ACTIVITIES`` and the workflow class, the common worker reads the histogram
metric config, the schedule bootstrap creates the code-workstreams schedule, and callers
trigger a run via ``execute_task_processing_workflow``. Isolated from ``facade/api.py`` so
``temporalio`` never lands on the light data-surface import path.
"""

from products.tasks.backend.temporal import ACTIVITIES, WORKFLOWS
from products.tasks.backend.temporal.client import (
    execute_task_processing_workflow,
    execute_task_processing_workflow_async,
)
from products.tasks.backend.temporal.code_workstreams.schedule import create_evaluate_code_workstreams_schedule
from products.tasks.backend.temporal.metrics import TASKS_LATENCY_HISTOGRAM_BUCKETS, TASKS_LATENCY_HISTOGRAM_METRICS
from products.tasks.backend.temporal.process_task.workflow import ProcessTaskWorkflow

__all__ = [
    "ACTIVITIES",
    "TASKS_LATENCY_HISTOGRAM_BUCKETS",
    "TASKS_LATENCY_HISTOGRAM_METRICS",
    "WORKFLOWS",
    "ProcessTaskWorkflow",
    "create_evaluate_code_workstreams_schedule",
    "execute_task_processing_workflow",
    "execute_task_processing_workflow_async",
]
