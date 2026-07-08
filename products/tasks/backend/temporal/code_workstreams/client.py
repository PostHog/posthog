import logging

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.client import sync_connect

from products.tasks.backend.temporal.code_workstreams.workflow import EvaluateTeamCodeWorkstreamsInput

logger = logging.getLogger(__name__)


def trigger_team_code_workstreams_evaluation(team_id: int) -> bool:
    client = sync_connect()
    workflow_id = f"evaluate-team-code-workstreams-ondemand-{team_id}"
    try:
        async_to_sync(client.start_workflow)(  # type: ignore[misc]
            "evaluate-team-code-workstreams",  # type: ignore[arg-type]
            EvaluateTeamCodeWorkstreamsInput(team_id=team_id),  # type: ignore[arg-type]
            id=workflow_id,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            task_queue=settings.TASKS_TASK_QUEUE,
        )
        return True
    except WorkflowAlreadyStartedError:
        logger.info("code_workstreams_refresh_already_running", extra={"team_id": team_id})
        return False
