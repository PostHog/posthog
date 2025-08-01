import asyncio
from typing import Optional
from temporalio.common import WorkflowIDReusePolicy, RetryPolicy

from posthog.temporal.common.client import async_connect
from posthog.constants import TASKS_TASK_QUEUE
from .inputs import TaskProcessingInputs


async def _execute_task_processing_workflow(
    task_id: str, team_id: int, previous_status: str, new_status: str, user_id: Optional[int] = None
) -> str:
    """Execute the task processing workflow asynchronously."""

    inputs = TaskProcessingInputs(
        task_id=task_id, team_id=team_id, previous_status=previous_status, new_status=new_status, user_id=user_id
    )

    # Create unique workflow ID based on task and timestamp
    import time

    workflow_id = f"task-processing-{task_id}-{int(time.time())}"

    client = await async_connect()

    retry_policy = RetryPolicy(maximum_attempts=3)

    result = await client.execute_workflow(
        "process-task-status-change",
        inputs,
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=TASKS_TASK_QUEUE,
        retry_policy=retry_policy,
    )

    return result


def execute_task_processing_workflow(
    task_id: str, team_id: int, previous_status: str, new_status: str, user_id: Optional[int] = None
) -> None:
    """
    Execute the task processing workflow synchronously.
    This is a fire-and-forget operation - it starts the workflow
    but doesn't wait for completion.
    """
    try:
        import logging

        logger = logging.getLogger(__name__)
        logger.info(f"Triggering workflow for task {task_id}: {previous_status} -> {new_status}")

        # Use asyncio.create_task for fire-and-forget in a new event loop
        # This avoids blocking the Django request
        try:
            loop = asyncio.get_running_loop()
            # We're in an async context, schedule the task
            loop.create_task(
                _execute_task_processing_workflow(task_id, team_id, previous_status, new_status, user_id)
            )
            logger.info(f"Scheduled workflow task for task {task_id}")
        except RuntimeError:
            # No running event loop, create one
            import threading

            def run_workflow():
                try:
                    asyncio.run(
                        _execute_task_processing_workflow(task_id, team_id, previous_status, new_status, user_id)
                    )
                    logger.info(f"Workflow completed for task {task_id}")
                except Exception as e:
                    logger.exception(f"Workflow execution failed for task {task_id}: {e}")

            # Run in a separate thread to avoid blocking Django
            thread = threading.Thread(target=run_workflow, daemon=True)
            thread.start()
            logger.info(f"Started workflow thread for task {task_id}")

    except Exception as e:
        # Don't let workflow execution failures break the main operation
        import logging

        logger = logging.getLogger(__name__)
        logger.exception(f"Failed to execute task processing workflow: {e}")
        # Don't re-raise to avoid breaking the API call
