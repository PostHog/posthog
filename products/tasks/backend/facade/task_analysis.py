"""Facade re-exports for the task-analysis explorer: the team's analysis runs and their flat rows."""

from products.tasks.backend.logic.services.task_analysis_runs import list_task_analysis_runs, task_analysis_run_row

__all__ = [
    "list_task_analysis_runs",
    "task_analysis_run_row",
]
