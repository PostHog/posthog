import uuid
import asyncio
import logging
from typing import TYPE_CHECKING, Any, Optional

from django.conf import settings
from django.db import transaction
from django.utils import timezone as django_timezone

import posthoganalytics
from asgiref.sync import sync_to_async
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.common.client import async_connect, sync_connect
from posthog.temporal.oauth import PosthogMcpScopes

from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.process_task.workflow import ProcessTaskInput
from products.tasks.backend.temporal.slack_relay.activities import RelaySlackMessageInput

if TYPE_CHECKING:
    from products.slack_app.backend.slack_thread import SlackThreadContext

logger = logging.getLogger(__name__)


_PRE_START_STATUSES: tuple[str, ...] = (TaskRun.Status.NOT_STARTED, TaskRun.Status.QUEUED)


def _normalize_slack_context(slack_thread_context: Optional[Any]) -> Optional[dict[str, Any]]:
    """Convert slack_thread_context to dict if needed."""
    if slack_thread_context is None:
        return None
    if hasattr(slack_thread_context, "to_dict"):
        return slack_thread_context.to_dict()
    return slack_thread_context


def _terminalize_unstarted_task_run(run_id: str, error_message: str) -> bool:
    try:
        with transaction.atomic():
            task_run = TaskRun.objects.select_for_update().get(id=run_id)
            if task_run.status not in _PRE_START_STATUSES:
                logger.info(
                    "task_processing_start_failure_not_terminalized",
                    extra={
                        "run_id": run_id,
                        "status": task_run.status,
                    },
                )
                return False

            task_run.status = TaskRun.Status.FAILED
            task_run.error_message = error_message
            task_run.completed_at = django_timezone.now()
            task_run.save(update_fields=["status", "error_message", "completed_at"])
    except TaskRun.DoesNotExist:
        logger.warning("task_processing_start_failure_task_run_missing", extra={"run_id": run_id})
        return False

    task_run.publish_stream_state_event()
    task_run.capture_event(
        "task_run_failed",
        {
            "error_message": error_message[:500],
            "duration_seconds": task_run._duration_seconds(),
        },
    )
    return True


async def _terminalize_unstarted_task_run_async(run_id: str, error_message: str) -> bool:
    return await sync_to_async(_terminalize_unstarted_task_run)(run_id, error_message)


async def execute_task_processing_workflow_async(
    task_id: str,
    run_id: str,
    team_id: int,
    user_id: Optional[int] = None,
    create_pr: bool = True,
    slack_thread_context: Optional[Any] = None,
    skip_user_check: bool = False,
    posthog_mcp_scopes: PosthogMcpScopes = "read_only",
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
                await _terminalize_unstarted_task_run_async(run_id, "Failed to start task workflow: missing user id")
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
            await _terminalize_unstarted_task_run_async(
                run_id,
                "Failed to start task workflow: tasks feature is disabled",
            )
            return

        workflow_id = TaskRun.get_workflow_id(task_id, run_id)
        slack_context_dict = _normalize_slack_context(slack_thread_context)

        workflow_input = ProcessTaskInput(
            run_id=run_id,
            create_pr=create_pr,
            slack_thread_context=slack_context_dict,
            posthog_mcp_scopes=posthog_mcp_scopes,
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
        await _terminalize_unstarted_task_run_async(
            run_id,
            f"Failed to start task workflow: permission validation failed: {e}",
        )
    except Exception as e:
        logger.exception(
            "task_processing_workflow_start_failed",
            extra={"task_id": task_id, "run_id": run_id, "error": str(e)},
        )
        await _terminalize_unstarted_task_run_async(
            run_id,
            f"Failed to start task workflow: {e}",
        )


def execute_task_processing_workflow(
    task_id: str,
    run_id: str,
    team_id: int,
    user_id: Optional[int] = None,
    create_pr: bool = True,
    slack_thread_context: Optional["SlackThreadContext"] = None,
    skip_user_check: bool = False,
    posthog_mcp_scopes: PosthogMcpScopes = "read_only",
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
                _terminalize_unstarted_task_run(run_id, "Failed to start task workflow: missing user id")
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
            _terminalize_unstarted_task_run(
                run_id,
                "Failed to start task workflow: tasks feature is disabled",
            )
            return

        workflow_id = TaskRun.get_workflow_id(task_id, run_id)
        slack_context_dict = _normalize_slack_context(slack_thread_context)

        workflow_input = ProcessTaskInput(
            run_id=run_id,
            create_pr=create_pr,
            slack_thread_context=slack_context_dict,
            posthog_mcp_scopes=posthog_mcp_scopes,
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
        _terminalize_unstarted_task_run(
            run_id,
            f"Failed to start task workflow: permission validation failed: {e}",
        )
    except Exception as e:
        logger.exception(
            "task_processing_workflow_start_failed",
            extra={"task_id": task_id, "run_id": run_id, "error": str(e)},
        )
        _terminalize_unstarted_task_run(
            run_id,
            f"Failed to start task workflow: {e}",
        )


def resume_task_in_cloud_workflow(run_id: str, workflow_id: str) -> None:
    client = sync_connect()
    asyncio.run(
        client.start_workflow(
            "process-task",
            ProcessTaskInput(run_id=run_id),
            id=workflow_id,
            # TERMINATE_IF_RUNNING closes any prior workflow under this ID
            # atomically before starting the new one, avoiding the async-cancel
            # race where a best-effort cancel signal hasn't landed yet.
            id_reuse_policy=WorkflowIDReusePolicy.TERMINATE_IF_RUNNING,
            task_queue=settings.TASKS_TASK_QUEUE,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
    )


def execute_posthog_code_agent_relay_workflow(
    run_id: str,
    text: str,
    relay_id: str | None = None,
    user_message_ts: str | None = None,
    delete_progress: bool = True,
    reaction_emoji: str = "hedgehog",
) -> str:
    relay_id = relay_id or str(uuid.uuid4())
    workflow_id = f"posthog-code-agent-relay-{run_id}-{relay_id}"

    client = sync_connect()
    asyncio.run(
        client.start_workflow(
            "posthog-code-agent-relay",
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
