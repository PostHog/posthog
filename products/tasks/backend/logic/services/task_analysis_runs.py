"""Read side of task analysis: the team's analysis runs, flattened for the explorer."""

from typing import Any

from django.db.models import QuerySet

from products.tasks.backend.constants import (
    ANALYSIS_TARGET_REPOSITORY_STATE_KEY,
    ANALYSIS_TARGET_RUN_ID_STATE_KEY,
    ANALYSIS_TARGET_TASK_ID_STATE_KEY,
    TASK_ANALYSIS_ACTIVITIES_STATE_KEY,
)
from products.tasks.backend.models import Task, TaskRun


def list_task_analysis_runs(team_id: int) -> QuerySet[TaskRun]:
    return TaskRun.objects.filter(team_id=team_id, task__origin_product=Task.OriginProduct.TASK_ANALYSIS).order_by(
        "-created_at"
    )


def task_analysis_run_row(run: TaskRun) -> dict[str, Any]:
    state = run.state if isinstance(run.state, dict) else {}
    activities = state.get(TASK_ANALYSIS_ACTIVITIES_STATE_KEY)
    return {
        "id": run.id,
        "task_id": run.task_id,
        "status": run.status,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
        "error_message": run.error_message,
        "runtime_adapter": state.get("runtime_adapter"),
        "model": state.get("model"),
        "reasoning_effort": state.get("reasoning_effort"),
        "target_task_id": state.get(ANALYSIS_TARGET_TASK_ID_STATE_KEY),
        "target_run_id": state.get(ANALYSIS_TARGET_RUN_ID_STATE_KEY),
        "target_repository": state.get(ANALYSIS_TARGET_REPOSITORY_STATE_KEY),
        "activities": [entry for entry in activities if isinstance(entry, dict)]
        if isinstance(activities, list)
        else [],
    }
