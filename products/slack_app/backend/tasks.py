import json

from django.core.cache import cache

import structlog
from asgiref.sync import async_to_sync
from celery import shared_task

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
def process_twig_mention(event: dict, integration_id: int, slack_team_id: str) -> None:
    """Process a Twig app_mention event asynchronously (local region only)."""
    from posthog.models.integration import Integration

    from products.slack_app.backend.api import handle_twig_app_mention

    integration = Integration.objects.select_related("team", "team__organization").get(
        id=integration_id,
        kind="slack-twig",
        integration_id=slack_team_id,
    )
    handle_twig_app_mention(event, integration)


@shared_task(ignore_result=True)
def process_twig_repo_selection(payload: dict) -> None:
    """Process a repo picker selection from Slack interactivity callback."""
    from posthog.models.integration import Integration, SlackIntegration

    from products.slack_app.backend.api import (
        _collect_thread_messages,
        _create_task_for_repo,
        _decode_picker_context,
        _extract_context_token,
        _get_full_repo_names,
        _set_user_default_repo,
        resolve_slack_user,
    )

    actions = payload.get("actions", [])
    action = next((a for a in actions if a.get("action_id") in {"twig_repo_select", "twig_default_repo_select"}), None)
    if not action:
        logger.warning("twig_repo_selection_no_action")
        return

    action_id = action.get("action_id", "")

    selected_repo = action.get("selected_option", {}).get("value", "")
    if not selected_repo:
        logger.warning("twig_repo_selection_no_value")
        return

    action_ts = action.get("action_ts", "")
    slack_user_id = payload.get("user", {}).get("id", "")
    slack_team_id = payload.get("team", {}).get("id")

    if not slack_team_id:
        logger.warning("twig_repo_selection_missing_slack_team")
        return

    context_token = _extract_context_token(payload)
    if not context_token:
        logger.warning("twig_repo_selection_no_token")
        return

    logger.info(
        "twig_repo_selection_dispatched",
        context_token=context_token,
        selected_repo=selected_repo,
        slack_user_id=slack_user_id,
    )

    ctx = _decode_picker_context(context_token)
    if not ctx:
        logger.info("twig_repo_selection_expired_token", context_token=context_token)
        return

    # Submit dedup
    dedup_key = f"twig_repo_select_submit:{context_token}:{action_ts}"
    if not cache.add(dedup_key, True, timeout=300):
        logger.info("twig_repo_selection_dedup", context_token=context_token)
        return

    # One-time consume
    used_key = f"twig_repo_picker_used:{context_token}"
    if not cache.add(used_key, True, timeout=900):
        logger.info("twig_repo_selection_already_used", context_token=context_token)
        return

    if slack_user_id != ctx["mentioning_slack_user_id"]:
        logger.warning(
            "twig_repo_selection_user_mismatch",
            expected=ctx["mentioning_slack_user_id"],
            actual=slack_user_id,
        )
        return

    try:
        integration = Integration.objects.select_related("team", "team__organization").get(
            id=ctx["integration_id"],
            kind="slack-twig",
            integration_id=slack_team_id,
        )
    except Integration.DoesNotExist:
        logger.warning("twig_repo_selection_no_integration", integration_id=ctx["integration_id"])
        return

    all_repos = _get_full_repo_names(integration)
    if selected_repo not in all_repos:
        logger.warning("twig_repo_selection_invalid_repo", repo=selected_repo)
        return

    slack = SlackIntegration(integration)
    channel = ctx["channel"]
    thread_ts = ctx["thread_ts"]

    user_context = resolve_slack_user(slack, integration, slack_user_id, channel, thread_ts)
    if not user_context:
        return

    auth_response = slack.client.auth_test()
    our_bot_id = auth_response.get("bot_id")
    thread_messages = _collect_thread_messages(slack, channel, thread_ts, our_bot_id)
    if not thread_messages:
        return

    # Update the picker message to show the selection
    picker_message_ts = payload.get("message", {}).get("ts")
    if picker_message_ts:
        try:
            selected_text = (
                f"Set default repository: `{selected_repo}`"
                if action_id == "twig_default_repo_select"
                else f"Selected repository: `{selected_repo}`"
            )
            slack.client.chat_update(
                channel=channel,
                ts=picker_message_ts,
                text=selected_text,
                blocks=[
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": selected_text},
                    }
                ],
            )
        except Exception:
            logger.warning("twig_repo_selection_update_failed", channel=channel)

    if action_id == "twig_default_repo_select":
        _set_user_default_repo(integration.team_id, user_context.user.id, selected_repo)
        try:
            slack.client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=(
                    f"Set your default repository to `{selected_repo}`. "
                    "You can change it with `@Twig default repo set org/repo` or clear with `@Twig default repo clear`."
                ),
            )
        except Exception:
            logger.warning("twig_default_repo_confirmation_failed", channel=channel)
        logger.info(
            "twig_default_repo_set_from_picker",
            context_token=context_token,
            selected_repo=selected_repo,
            team_id=integration.team_id,
            channel=channel,
        )
        return

    logger.info(
        "twig_repo_selection_processing",
        context_token=context_token,
        selected_repo=selected_repo,
        team_id=integration.team_id,
        channel=channel,
    )

    _create_task_for_repo(
        repository=selected_repo,
        integration=integration,
        slack=slack,
        channel=channel,
        thread_ts=thread_ts,
        user_message_ts=ctx.get("user_message_ts"),
        event_text=ctx.get("event_text", ""),
        thread_messages=thread_messages,
        user_id=user_context.user.id,
        slack_user_id=slack_user_id,
    )


@shared_task(ignore_result=True)
def process_twig_task_termination(payload: dict) -> None:
    """Terminate a running task workflow from Slack interactivity action."""
    from posthog.temporal.common.client import sync_connect

    from products.tasks.backend.temporal.process_task.workflow import ProcessTaskWorkflow

    actions = payload.get("actions", [])
    action = next((a for a in actions if a.get("action_id") == "twig_terminate_task"), None)
    if not action:
        logger.warning("twig_terminate_no_action")
        return

    action_value = action.get("value", "")
    if not action_value:
        logger.warning("twig_terminate_no_value")
        return

    try:
        value = json.loads(action_value)
    except json.JSONDecodeError:
        logger.warning("twig_terminate_invalid_value")
        return

    run_id = value.get("run_id")
    integration_id = value.get("integration_id")
    expected_user_id = value.get("mentioning_slack_user_id")
    thread_ts_from_value = value.get("thread_ts")
    requesting_user_id = payload.get("user", {}).get("id")
    slack_team_id = payload.get("team", {}).get("id")

    if not run_id or not integration_id:
        logger.warning("twig_terminate_missing_context", run_id=run_id, integration_id=integration_id)
        return

    if not slack_team_id:
        logger.warning("twig_terminate_missing_slack_team", run_id=run_id)
        return

    if expected_user_id and requesting_user_id and expected_user_id != requesting_user_id:
        logger.warning(
            "twig_terminate_user_mismatch",
            expected=expected_user_id,
            actual=requesting_user_id,
            run_id=run_id,
        )
        return

    from posthog.models.integration import Integration, SlackIntegration

    from products.tasks.backend.models import TaskRun

    try:
        integration = Integration.objects.get(id=integration_id, kind="slack-twig", integration_id=slack_team_id)
    except Integration.DoesNotExist:
        logger.warning("twig_terminate_integration_not_found", integration_id=integration_id)
        return

    channel = payload.get("channel", {}).get("id") or payload.get("container", {}).get("channel_id")
    message_ts = payload.get("message", {}).get("ts")
    thread_ts = thread_ts_from_value or payload.get("message", {}).get("thread_ts") or message_ts

    try:
        task_run = TaskRun.objects.select_related("task").get(id=run_id, team_id=integration.team_id)
    except TaskRun.DoesNotExist:
        logger.warning("twig_terminate_run_not_found", run_id=run_id)
        return

    if task_run.status in {
        TaskRun.Status.COMPLETED,
        TaskRun.Status.FAILED,
        TaskRun.Status.CANCELLED,
    }:
        logger.info("twig_terminate_run_already_terminal", run_id=run_id, status=task_run.status)
        if channel and thread_ts:
            try:
                slack_client = SlackIntegration(integration).client
                slack_client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=f"This run is already `{task_run.status}`. There is nothing to terminate.",
                )
            except Exception:
                logger.warning("twig_terminate_terminal_feedback_failed", run_id=run_id)
        return

    try:
        client = sync_connect()
        workflow_id = f"task-processing-{task_run.task_id}-{task_run.id}"
        handle = client.get_workflow_handle(workflow_id)
        async_to_sync(handle.signal)(
            ProcessTaskWorkflow.complete_task,
            args=["cancelled", "Run terminated from Slack"],
        )
        logger.info("twig_terminate_signaled", run_id=run_id, workflow_id=workflow_id)
    except Exception as e:
        logger.exception("twig_terminate_signal_failed", run_id=run_id, error=str(e))
        return

    if channel and message_ts:
        try:
            slack_client = SlackIntegration(integration).client
            progress_text = "*Working on task...* :hourglass_flowing_sand:\nTermination requested. Stopping run and cleaning up sandbox..."
            slack_client.chat_update(
                channel=channel,
                ts=message_ts,
                text=progress_text,
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": progress_text,
                        },
                    }
                ],
            )
        except Exception:
            logger.warning("twig_terminate_message_update_failed", run_id=run_id)
