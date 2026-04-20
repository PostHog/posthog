from temporalio import activity

from posthog.temporal.common.utils import asyncify


@activity.defn
@asyncify
def run_task_automation_activity(automation_id: str) -> None:
    from ...automation_service import run_task_automation

    run_task_automation(automation_id, trigger_workflow_id=activity.info().workflow_id)
