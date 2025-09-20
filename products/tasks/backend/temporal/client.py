import asyncio
from typing import Optional

from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.constants import TASKS_TASK_QUEUE
from posthog.temporal.common.client import async_connect

from .inputs import TaskProcessingInputs


async def _execute_task_processing_workflow(task_id: str, team_id: int, user_id: Optional[int] = None) -> str:
    """Execute the task processing workflow asynchronously."""

    inputs = TaskProcessingInputs(task_id=task_id, team_id=team_id, user_id=user_id)

    # Create unique workflow ID based on task and timestamp
    import time, uuid, logging

    # Use high-resolution timestamp + random suffix to avoid collisions when re-triggering within the same second
    workflow_id = f"task-processing-{task_id}-{int(time.time()*1000)}-{uuid.uuid4().hex[:8]}"

    logging.getLogger(__name__).info(f"Starting workflow {workflow_id} for task {task_id}")

    client = await async_connect()

    retry_policy = RetryPolicy(maximum_attempts=3)

    result = await client.execute_workflow(
        "process-task-workflow-agnostic",
        inputs,
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=TASKS_TASK_QUEUE,
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
        import logging
        import threading

        logger = logging.getLogger(__name__)
        logger.info(f"Triggering workflow for task {task_id}")

        # Always offload to a dedicated thread with its own event loop.
        # This is safer when called from within a Temporal activity (already running an event loop)
        # and from sync Django views. It avoids create_task() being cancelled when the caller loop ends.
        def run_workflow() -> None:
            try:
                asyncio.run(_execute_task_processing_workflow(task_id, team_id, user_id))
                logger.info(f"Workflow completed for task {task_id}")
            except Exception as e:
                logger.exception(f"Workflow execution failed for task {task_id}: {e}")

        thread = threading.Thread(target=run_workflow, daemon=True)
        thread.start()
        logger.info(f"Started workflow thread for task {task_id}")

    except Exception as e:
        # Don't let workflow execution failures break the main operation
        import logging

        logger = logging.getLogger(__name__)
        logger.exception(f"Failed to execute task processing workflow: {e}")
        # Don't re-raise to avoid breaking the API call
