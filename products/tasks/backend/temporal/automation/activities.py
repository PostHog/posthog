from django.core.exceptions import PermissionDenied

from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.utils import asyncify


@activity.defn
@asyncify
def run_task_automation_activity(automation_id: str) -> None:
    from ...automation_service import run_task_automation

    try:
        run_task_automation(automation_id, trigger_workflow_id=activity.info().workflow_id)
    except PermissionDenied as e:
        raise ApplicationError(str(e), type="AutomationAccessRevoked", non_retryable=True) from e
