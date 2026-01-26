import uuid
import asyncio
import logging
from typing import TYPE_CHECKING, Any, Optional

from django.conf import settings

import posthoganalytics
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.service import RPCError

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.common.client import async_connect, sync_connect

from products.tasks.backend.temporal.process_task.workflow import ProcessTaskInput

if TYPE_CHECKING:
    from products.slack_app.backend.slack_thread import SlackThreadContext

logger = logging.getLogger(__name__)


def _normalize_slack_context(slack_thread_context: Optional[Any]) -> Optional[dict[str, Any]]:
    """Convert slack_thread_context to dict if needed."""
    if slack_thread_context is None:
        return None
    if hasattr(slack_thread_context, "to_dict"):
        return slack_thread_context.to_dict()
    return slack_thread_context


async def execute_task_processing_workflow_async(
    task_id: str,
    run_id: str,
    team_id: int,
    user_id: Optional[int] = None,
    create_pr: bool = True,
    slack_thread_context: Optional[Any] = None,
) -> None:
    """
    Start the task processing workflow asynchronously. Fire-and-forget.
    Use this from async contexts (e.g., within Temporal activities).
    """
    logger.info(f"execute_task_processing_workflow_async called for task {task_id}, run {run_id}")
    try:
        if not user_id:
            logger.warning(f"No user_id provided for task {task_id} - tasks require authenticated user")
            return

        logger.info(f"Fetching team {team_id} and user {user_id}")
        team = await Team.objects.select_related("organization").aget(id=team_id)
        user = await User.objects.aget(id=user_id)

        logger.info(f"Checking feature flag for user {user.distinct_id}, org {team.organization_id}")
        tasks_enabled = posthoganalytics.feature_enabled(
            "tasks",
            user.distinct_id,
            groups={"organization": str(team.organization_id)},
            group_properties={"organization": {"id": str(team.organization_id)}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
        logger.info(f"Feature flag 'tasks' enabled: {tasks_enabled}")

        if not tasks_enabled:
            logger.warning(
                f"Task workflow execution blocked for task {task_id} - feature flag 'tasks' not enabled for user {user_id}"
            )
            return

        workflow_id = f"task-processing-{task_id}-{run_id}"
        slack_context_dict = _normalize_slack_context(slack_thread_context)

        workflow_input = ProcessTaskInput(
            run_id=run_id,
            create_pr=create_pr,
            slack_thread_context=slack_context_dict,
        )

        logger.info(f"Starting workflow process-task ({workflow_id}) for task {task_id}, run {run_id}")

        client = await async_connect()
        await client.start_workflow(
            "process-task",
            workflow_input,
            id=workflow_id,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            task_queue=settings.TASKS_TASK_QUEUE,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        logger.info(f"Workflow started for task {task_id}, run {run_id}")

    except (Team.DoesNotExist, User.DoesNotExist) as e:
        logger.exception(f"Failed to validate permissions for task workflow execution: {e}")
    except Exception as e:
        logger.exception(f"Failed to start task processing workflow: {e}")


def execute_task_processing_workflow(
    task_id: str,
    run_id: str,
    team_id: int,
    user_id: Optional[int] = None,
    create_pr: bool = True,
    slack_thread_context: Optional["SlackThreadContext"] = None,
) -> None:
    """
    Start the task processing workflow synchronously. Fire-and-forget.
    Use this from sync contexts (e.g., API endpoints).
    """
    try:
        if not user_id:
            logger.warning(f"No user_id provided for task {task_id} - tasks require authenticated user")
            return

        team = Team.objects.get(id=team_id)
        user = User.objects.get(id=user_id)

        tasks_enabled = posthoganalytics.feature_enabled(
            "tasks",
            user.distinct_id,
            groups={"organization": str(team.organization.id)},
            group_properties={"organization": {"id": str(team.organization.id)}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )

        if not tasks_enabled:
            logger.warning(
                f"Task workflow execution blocked for task {task_id} - feature flag 'tasks' not enabled for user {user_id}"
            )
            return

        workflow_id = f"task-processing-{task_id}-{run_id}"
        slack_context_dict = _normalize_slack_context(slack_thread_context)

        workflow_input = ProcessTaskInput(
            run_id=run_id,
            create_pr=create_pr,
            slack_thread_context=slack_context_dict,
        )

        logger.info(f"Starting workflow process-task ({workflow_id}) for task {task_id}, run {run_id}")

        client = sync_connect()
        asyncio.run(
            client.start_workflow(
                "process-task",
                workflow_input,
                id=workflow_id,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                task_queue=settings.TASKS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        )

        logger.info(f"Workflow started for task {task_id}, run {run_id}")

    except (Team.DoesNotExist, User.DoesNotExist) as e:
        logger.exception(f"Failed to validate permissions for task workflow execution: {e}")
    except Exception as e:
        logger.exception(f"Failed to start task processing workflow: {e}")


def execute_cloud_workflow(
    task_id: str,
    run_id: str,
    team_id: int,
    initial_prompt: Optional[str] = None,
) -> Optional[str]:
    """
    Start a cloud execution workflow for the given run.

    Uses a UUID suffix to allow multiple workflows per run_id (for hibernation/resume).
    Returns the workflow_id if started successfully, None otherwise.
    """
    try:
        workflow_uuid = uuid.uuid4().hex[:8]
        workflow_id = f"task-processing-{run_id}-{workflow_uuid}"

        workflow_input = ProcessTaskInput(
            run_id=run_id,
            create_pr=True,
            execution_mode="cloud",
            initial_prompt=initial_prompt,
        )

        logger.info(f"Starting cloud workflow ({workflow_id}) for task {task_id}, run {run_id}")

        client = sync_connect()
        asyncio.run(
            client.start_workflow(
                "process-task",
                workflow_input,
                id=workflow_id,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                task_queue=settings.TASKS_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        )

        logger.info(f"Cloud workflow started: {workflow_id}")
        return workflow_id

    except Exception as e:
        logger.exception(f"Failed to start cloud workflow: {e}")
        return None


async def send_process_task_heartbeat_async(run_id: str, workflow_id: str) -> bool:
    """Send a heartbeat signal to keep the process-task workflow alive."""
    try:
        client = await async_connect()
        handle = client.get_workflow_handle(workflow_id)
        await handle.signal("heartbeat")
        logger.debug(f"Heartbeat sent to process-task workflow {workflow_id}")
        return True
    except RPCError as e:
        logger.warning(f"Failed to send heartbeat to process-task workflow {workflow_id}: {e}")
        return False
    except Exception as e:
        logger.warning(f"Failed to send heartbeat to process-task workflow {workflow_id}: {e}")
        return False


def send_process_task_heartbeat(run_id: str, workflow_id: str) -> bool:
    """Send a heartbeat signal to keep the process-task workflow alive (sync version)."""
    try:
        client = sync_connect()
        handle = client.get_workflow_handle(workflow_id)
        asyncio.get_event_loop().run_until_complete(handle.signal("heartbeat"))
        logger.debug(f"Heartbeat sent to process-task workflow {workflow_id}")
        return True
    except RPCError as e:
        logger.warning(f"Failed to send heartbeat to process-task workflow {workflow_id}: {e}")
        return False
    except Exception as e:
        logger.warning(f"Failed to send heartbeat to process-task workflow {workflow_id}: {e}")
        return False


async def is_workflow_running_async(workflow_id: str) -> bool:
    """Check if a workflow is currently running."""
    try:
        client = await async_connect()
        handle = client.get_workflow_handle(workflow_id)
        desc = await handle.describe()
        return desc.status.name == "RUNNING"
    except RPCError:
        return False
    except Exception:
        return False


def is_workflow_running(workflow_id: str) -> bool:
    """Check if a workflow is currently running (sync version)."""
    try:
        client = sync_connect()
        handle = client.get_workflow_handle(workflow_id)
        desc = asyncio.run(handle.describe())
        return desc.status.name == "RUNNING"
    except RPCError:
        return False
    except Exception:
        return False
