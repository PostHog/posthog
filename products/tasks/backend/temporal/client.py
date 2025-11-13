import time
import uuid
import asyncio
import logging
from typing import Optional

from django.conf import settings

import posthoganalytics
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.common.client import async_connect

logger = logging.getLogger(__name__)


async def _execute_task_processing_workflow(task_id: str, team_id: int, user_id: Optional[int] = None) -> str:
    workflow_id = f"task-processing-{task_id}-{int(time.time()*1000)}-{uuid.uuid4().hex[:8]}"
    workflow_name = "process-task"
    workflow_input = task_id

    logger.info(f"Starting workflow {workflow_name} ({workflow_id}) for task {task_id}")

    client = await async_connect()

    retry_policy = RetryPolicy(maximum_attempts=3)

    result = await client.execute_workflow(
        workflow_name,
        workflow_input,
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=settings.TASKS_TASK_QUEUE,
        retry_policy=retry_policy,
    )

    return result


def execute_task_processing_workflow(task_id: str, team_id: int, user_id: Optional[int] = None) -> None:
    """
    Execute the task processing workflow synchronously.
    This is a fire-and-forget operation - it starts the workflow
    but doesn't wait for completion.
    """
    try:
        import threading

        # Always offload to a dedicated thread with its own event loop.
        # This is safer when called from within a Temporal activity (already running an event loop)
        # and from sync Django views. It avoids create_task() being cancelled when the caller loop ends.
        def run_workflow() -> None:
            try:
                # Check feature flag in the thread where we can make sync Django calls

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

                except (Team.DoesNotExist, User.DoesNotExist) as e:
                    logger.exception(f"Failed to validate permissions for task workflow execution: {e}")
                    return
                except Exception as e:
                    logger.exception(f"Error checking feature flag for task workflow: {e}")
                    return

                logger.info(f"Triggering workflow for task {task_id}")
                asyncio.run(_execute_task_processing_workflow(task_id, team_id, user_id))
                logger.info(f"Workflow completed for task {task_id}")
            except Exception as e:
                logger.exception(f"Workflow execution failed for task {task_id}: {e}")

        thread = threading.Thread(target=run_workflow, daemon=True)
        thread.start()
        logger.info(f"Started workflow thread for task {task_id}")

    except Exception as e:
        # Don't let workflow execution failures break the main operation
        logger.exception(f"Failed to execute task processing workflow: {e}")
