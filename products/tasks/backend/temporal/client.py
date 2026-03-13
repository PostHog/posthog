import uuid
import asyncio
import logging
from typing import TYPE_CHECKING, Any, Optional

from django.conf import settings

import posthoganalytics
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.common.client import async_connect, sync_connect

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.process_task.workflow import ProcessTaskInput
from products.tasks.backend.temporal.slack_relay.activities import RelaySlackMessageInput

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
    skip_user_check: bool = False,
) -> None:
    """
    Start the task processing workflow asynchronously. Fire-and-forget.
    Use this from async contexts (e.g., within Temporal activities).

    Args:
        skip_user_check: If True, skip user-based feature flag check. Use for automated/system tasks.
    """
    logger.info(
        "execute_task_processing_workflow_async_called",
        extra={"task_id": task_id, "run_id": run_id},
    )
    try:
        team = await Team.objects.select_related("organization").aget(id=team_id)

        if skip_user_check:
            logger.info("task_processing_skip_user_check", extra={"task_id": task_id, "team_id": team_id})
            tasks_enabled = posthoganalytics.feature_enabled(
                "tasks",
                f"team_{team_id}",
                groups={"organization": str(team.organization_id)},
                group_properties={"organization": {"id": str(team.organization_id)}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        else:
            if not user_id:
                logger.warning("task_processing_missing_user_id", extra={"task_id": task_id})
                return

            logger.info("task_processing_fetching_team_and_user", extra={"team_id": team_id, "user_id": user_id})
            user = await User.objects.aget(id=user_id)

            logger.info(
                "task_processing_checking_feature_flag",
                extra={"distinct_id": user.distinct_id, "organization_id": team.organization_id},
            )
            tasks_enabled = posthoganalytics.feature_enabled(
                "tasks",
                user.distinct_id,
                groups={"organization": str(team.organization_id)},
                group_properties={"organization": {"id": str(team.organization_id)}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )

        logger.info("task_processing_feature_flag_result", extra={"task_id": task_id, "tasks_enabled": tasks_enabled})

        if not tasks_enabled:
            logger.warning("task_processing_blocked_feature_flag", extra={"task_id": task_id})
            return

        workflow_id = TaskRun.get_workflow_id(task_id, run_id)
        slack_context_dict = _normalize_slack_context(slack_thread_context)

        workflow_input = ProcessTaskInput(
            run_id=run_id,
            create_pr=create_pr,
            slack_thread_context=slack_context_dict,
        )

        logger.info(
            "task_processing_starting_workflow",
            extra={"workflow_id": workflow_id, "task_id": task_id, "run_id": run_id},
        )

        client = await async_connect()
        await client.start_workflow(
            "process-task",
            workflow_input,
            id=workflow_id,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            task_queue=settings.TASKS_TASK_QUEUE,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        logger.info("task_processing_workflow_started", extra={"task_id": task_id, "run_id": run_id})

    except (Team.DoesNotExist, User.DoesNotExist) as e:
        logger.exception(
            "task_processing_permission_validation_failed",
            extra={"task_id": task_id, "run_id": run_id, "error": str(e)},
        )
    except Exception as e:
        logger.exception(
            "task_processing_workflow_start_failed",
            extra={"task_id": task_id, "run_id": run_id, "error": str(e)},
        )


def execute_task_processing_workflow(
    task_id: str,
    run_id: str,
    team_id: int,
    user_id: Optional[int] = None,
    create_pr: bool = True,
    slack_thread_context: Optional["SlackThreadContext"] = None,
    skip_user_check: bool = False,
) -> None:
    """
    Start the task processing workflow synchronously. Fire-and-forget.
    Use this from sync contexts (e.g., API endpoints).

    Args:
        skip_user_check: If True, skip user-based feature flag check. Use for automated/system tasks.
    """
    try:
        logger.info(
            "execute_task_processing_workflow_called",
            extra={"task_id": task_id, "run_id": run_id, "team_id": team_id, "user_id": user_id},
        )

        team = Team.objects.get(id=team_id)

        if settings.DEBUG:
            logger.info("task_processing_debug_skip_feature_flag", extra={"task_id": task_id})
            tasks_enabled = True
        elif skip_user_check:
            logger.info("task_processing_skip_user_check", extra={"task_id": task_id, "team_id": team_id})
            tasks_enabled = posthoganalytics.feature_enabled(
                "tasks",
                f"team_{team_id}",
                groups={"organization": str(team.organization.id)},
                group_properties={"organization": {"id": str(team.organization.id)}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        else:
            if not user_id:
                logger.warning("task_processing_missing_user_id", extra={"task_id": task_id})
                return

            user = User.objects.get(id=user_id)

            tasks_enabled = posthoganalytics.feature_enabled(
                "tasks",
                user.distinct_id,
                groups={"organization": str(team.organization.id)},
                group_properties={"organization": {"id": str(team.organization.id)}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )

        logger.info("task_processing_feature_flag_result", extra={"task_id": task_id, "tasks_enabled": tasks_enabled})

        if not tasks_enabled:
            logger.warning("task_processing_blocked_feature_flag", extra={"task_id": task_id})
            return

        workflow_id = TaskRun.get_workflow_id(task_id, run_id)
        slack_context_dict = _normalize_slack_context(slack_thread_context)

        workflow_input = ProcessTaskInput(
            run_id=run_id,
            create_pr=create_pr,
            slack_thread_context=slack_context_dict,
        )

        logger.info(
            "task_processing_connecting_temporal",
            extra={"task_id": task_id, "task_queue": settings.TASKS_TASK_QUEUE},
        )

        client = sync_connect()

        logger.info(
            "task_processing_temporal_connected",
            extra={"workflow_id": workflow_id, "task_id": task_id, "run_id": run_id},
        )

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

        logger.info("task_processing_workflow_started", extra={"task_id": task_id, "run_id": run_id})

    except (Team.DoesNotExist, User.DoesNotExist) as e:
        logger.exception(
            "task_processing_permission_validation_failed",
            extra={"task_id": task_id, "run_id": run_id, "error": str(e)},
        )
    except Exception as e:
        logger.exception(
            "task_processing_workflow_start_failed",
            extra={"task_id": task_id, "run_id": run_id, "error": str(e)},
        )


def execute_video_segment_clustering_workflow(team_id: int, skip_priming: bool = False) -> dict[str, Any]:
    """
    Execute the video segment clustering workflow for a single team synchronously.
    Waits for the workflow to complete and returns the result.

    Args:
        team_id: Team ID to run clustering for
        lookback_hours: How far back to look for segments. If None, uses default from constants.
        skip_priming: If True, skip the session summarization priming step.
    """
    from datetime import datetime

    from posthog.temporal.ai.video_segment_clustering import constants
    from posthog.temporal.ai.video_segment_clustering.models import ClusteringWorkflowInputs

    try:
        workflow_id = f"video-segment-clustering-team-{team_id}-manual-{datetime.now().isoformat()}"

        workflow_input = ClusteringWorkflowInputs(
            team_id=team_id,
            min_segments=constants.MIN_SEGMENTS_FOR_CLUSTERING,
            skip_priming=skip_priming,
        )

        logger.info("video_clustering_starting_workflow", extra={"workflow_id": workflow_id, "team_id": team_id})

        client = sync_connect()
        handle = asyncio.run(
            client.start_workflow(
                "video-segment-clustering",
                workflow_input,
                id=workflow_id,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        )

        logger.info(
            "video_clustering_workflow_started_waiting",
            extra={"workflow_id": workflow_id, "team_id": team_id},
        )

        # Wait for workflow completion and get result
        result = asyncio.run(handle.result())

        logger.info("video_clustering_workflow_completed", extra={"workflow_id": workflow_id, "team_id": team_id})
        return {"workflow_id": workflow_id, "run_id": handle.result_run_id, **result}

    except Exception as e:
        logger.exception("video_clustering_workflow_failed", extra={"team_id": team_id, "error": str(e)})
        raise


def execute_twig_agent_relay_workflow(
    run_id: str,
    text: str,
    relay_id: str | None = None,
    user_message_ts: str | None = None,
    delete_progress: bool = True,
    reaction_emoji: str = "white_check_mark",
) -> str:
    relay_id = relay_id or str(uuid.uuid4())
    workflow_id = f"twig-agent-relay-{run_id}-{relay_id}"

    client = sync_connect()
    asyncio.run(
        client.start_workflow(
            "twig-agent-relay",
            RelaySlackMessageInput(
                run_id=run_id,
                relay_id=relay_id,
                text=text,
                user_message_ts=user_message_ts,
                delete_progress=delete_progress,
                reaction_emoji=reaction_emoji,
            ),
            id=workflow_id,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            task_queue=settings.TASKS_TASK_QUEUE,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
    )
    return relay_id
