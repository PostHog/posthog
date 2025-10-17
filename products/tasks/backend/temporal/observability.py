from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Optional

import posthoganalytics
from temporalio import activity, workflow

from posthog.temporal.common.logger import get_logger

logger = get_logger(__name__)


def get_bound_logger(**context: Any):
    return logger.bind(**context)


def log_with_activity_context(message: str, **extra_context: Any) -> None:
    bound_logger = logger.bind(**extra_context)

    if activity.in_activity():
        info = activity.info()
        bound_logger = bound_logger.bind(
            activity_id=info.activity_id,
            activity_type=info.activity_type,
            attempt=info.attempt,
        )

    bound_logger.info(message)


def log_with_workflow_context(message: str, **extra_context: Any) -> None:
    bound_logger = logger.bind(**extra_context)

    if workflow.in_workflow():
        info = workflow.info()
        bound_logger = bound_logger.bind(
            workflow_id=info.workflow_id,
            workflow_run_id=info.run_id,
            workflow_type=info.workflow_type,
        )

    bound_logger.info(message)


@asynccontextmanager
async def log_activity_execution(
    activity_name: str,
    distinct_id: Optional[str] = None,
    **context: Any,
) -> AsyncIterator[None]:
    """Context manager for activity execution with automatic logging and analytics.

    Automatically tracks:
    - process_task_activity_started
    - process_task_activity_completed
    - process_task_activity_failed

    Usage:
        async with log_activity_execution(
            "clone_repository",
            distinct_id=f"user_{user_id}",
            task_id=task_id,
            repository=repo
        ):
            result = await do_work()
            return result
    """
    bound_logger = logger.bind(**context)

    if activity.in_activity():
        info = activity.info()
        bound_logger = bound_logger.bind(
            activity_id=info.activity_id,
            activity_type=info.activity_type,
            attempt=info.attempt,
        )

    bound_logger.info(f"{activity_name} started")

    if distinct_id:
        track_event(
            "process_task_activity_started",
            distinct_id=distinct_id,
            properties={"activity_name": activity_name, **context},
        )

    try:
        yield
        bound_logger.info(f"{activity_name} completed successfully")

        if distinct_id:
            track_event(
                "process_task_activity_completed",
                distinct_id=distinct_id,
                properties={"activity_name": activity_name, **context},
            )
    except Exception as e:
        bound_logger.exception(
            f"{activity_name} failed",
            error_type=type(e).__name__,
            error_message=str(e),
        )

        if distinct_id:
            track_event(
                "process_task_activity_failed",
                distinct_id=distinct_id,
                properties={
                    "activity_name": activity_name,
                    "error_type": type(e).__name__,
                    "error_message": str(e)[:500],
                    **context,
                },
            )

        raise


def track_event(
    event_name: str,
    distinct_id: str,
    properties: Optional[dict[str, Any]] = None,
) -> None:
    try:
        enriched_properties = {**(properties or {})}

        if activity.in_activity():
            activity_info = activity.info()
            enriched_properties.update(
                {
                    "temporal_activity_id": activity_info.activity_id,
                    "temporal_activity_type": activity_info.activity_type,
                    "temporal_workflow_id": activity_info.workflow_id,
                    "temporal_workflow_run_id": activity_info.workflow_run_id,
                    "temporal_attempt": activity_info.attempt,
                }
            )
        elif workflow.in_workflow() and not workflow.unsafe.is_replaying():
            workflow_info = workflow.info()
            enriched_properties.update(
                {
                    "temporal_workflow_id": workflow_info.workflow_id,
                    "temporal_workflow_run_id": workflow_info.run_id,
                    "temporal_workflow_type": workflow_info.workflow_type,
                }
            )

        posthoganalytics.capture(
            distinct_id=distinct_id,
            event=event_name,
            properties=enriched_properties,
        )

        logger.debug(f"Tracked event: {event_name}", **enriched_properties)

    except Exception as e:
        logger.warning(f"Failed to track event {event_name}", exc_info=e)
