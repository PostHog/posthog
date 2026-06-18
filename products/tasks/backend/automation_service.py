import logging

from django.conf import settings
from django.db import transaction

from temporalio.client import Schedule, ScheduleActionStartWorkflow, ScheduleSpec, ScheduleState

from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.schedule import (
    create_schedule,
    delete_schedule,
    pause_schedule,
    schedule_exists,
    unpause_schedule,
    update_schedule,
)

from .models import Task, TaskAutomation, TaskRun

logger = logging.getLogger(__name__)


def build_automation_schedule(automation: TaskAutomation) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            "run-task-automation",
            str(automation.id),
            id=f'task-automation-run-{automation.id}-{{{{.ScheduledTime.Format "2006-01-02-15-04"}}}}',
            task_queue=settings.TASKS_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            cron_expressions=[automation.cron_expression],
            time_zone_name=automation.timezone,
        ),
        state=ScheduleState(
            paused=not automation.enabled,
            note=f"Schedule for task automation: {automation.id}",
        ),
    )


def sync_automation_schedule(automation: TaskAutomation) -> None:
    temporal = sync_connect()
    schedule = build_automation_schedule(automation)

    if schedule_exists(temporal, automation.schedule_id):
        update_schedule(temporal, automation.schedule_id, schedule)
        if automation.enabled:
            unpause_schedule(temporal, automation.schedule_id, note="Automation enabled")
        else:
            pause_schedule(temporal, automation.schedule_id, note="Automation paused")
    else:
        create_schedule(temporal, automation.schedule_id, schedule)


def delete_automation_schedule(automation: TaskAutomation) -> None:
    temporal = sync_connect()
    if schedule_exists(temporal, automation.schedule_id):
        delete_schedule(temporal, automation.schedule_id)


def run_task_automation(automation_id: str, trigger_workflow_id: str | None = None) -> tuple[Task, TaskRun]:
    automation_id = str(automation_id)
    with transaction.atomic():
        automation = TaskAutomation.objects.select_for_update(of=("self",)).select_related("task").get(id=automation_id)
        task = automation.task

        if trigger_workflow_id:
            existing_task_run_query = TaskRun.objects.select_related("task").filter(
                task__team_id=task.team_id,
                task_id=task.id,
                state__automation_id=automation_id,
                state__automation_trigger_workflow_id=trigger_workflow_id,
            )
            existing_task_run = existing_task_run_query.order_by("-created_at").first()
            if existing_task_run is not None:
                task_run = existing_task_run
            else:
                extra_state = {"automation_id": automation_id}
                if trigger_workflow_id:
                    extra_state["automation_trigger_workflow_id"] = trigger_workflow_id
                task_run = task.create_run(mode="background", extra_state=extra_state)
        else:
            task_run = task.create_run(mode="background", extra_state={"automation_id": automation_id})

        team_id = task.team_id
        user_id = task.created_by_id

        automation.last_task_run = task_run
        automation.last_error = None
        automation.save(
            update_fields=[
                "last_task_run",
                "last_error",
                "updated_at",
            ]
        )

        transaction.on_commit(
            lambda: execute_task_processing_workflow_for_automation(
                team_id=team_id,
                user_id=user_id,
                task_id=str(task.id),
                run_id=str(task_run.id),
            )
        )

    logger.info(
        "task_automation_run_started",
        extra={
            "automation_id": automation_id,
            "task_id": str(task.id),
            "run_id": str(task_run.id),
            "team_id": team_id,
        },
    )

    return task, task_run


def execute_task_processing_workflow_for_automation(
    *, team_id: int, user_id: int | None, task_id: str, run_id: str
) -> None:
    from .temporal.client import execute_task_processing_workflow

    execute_task_processing_workflow(
        task_id=task_id,
        run_id=run_id,
        team_id=team_id,
        user_id=user_id,
        skip_user_check=True,
    )


def update_automation_run_result(task_run: TaskRun) -> None:
    if task_run.task.origin_product != Task.OriginProduct.AUTOMATION:
        return

    try:
        automation = task_run.task.automation
    except TaskAutomation.DoesNotExist:
        return

    if task_run.status not in [TaskRun.Status.FAILED, TaskRun.Status.CANCELLED]:
        return

    automation.last_error = task_run.error_message
    automation.save(update_fields=["last_error", "updated_at"])
