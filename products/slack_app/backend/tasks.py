from django.core.cache import cache

import structlog
from celery import shared_task

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
def process_twig_mention(event: dict, integration_id: int) -> None:
    """Process a Twig app_mention event asynchronously (local region only)."""
    from posthog.models.integration import Integration

    from products.slack_app.backend.api import handle_twig_app_mention

    integration = Integration.objects.select_related("team", "team__organization").get(id=integration_id)
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
        resolve_slack_user,
    )

    actions = payload.get("actions", [])
    action = next((a for a in actions if a.get("action_id") == "twig_repo_select"), None)
    if not action:
        logger.warning("twig_repo_selection_no_action")
        return

    selected_repo = action.get("selected_option", {}).get("value", "")
    if not selected_repo:
        logger.warning("twig_repo_selection_no_value")
        return

    action_ts = action.get("action_ts", "")
    slack_user_id = payload.get("user", {}).get("id", "")

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
        integration = Integration.objects.select_related("team", "team__organization").get(id=ctx["integration_id"])
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
            slack.client.chat_update(
                channel=channel,
                ts=picker_message_ts,
                text=f"Selected repository: `{selected_repo}`",
                blocks=[
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"Selected repository: `{selected_repo}`"},
                    }
                ],
            )
        except Exception:
            logger.warning("twig_repo_selection_update_failed", channel=channel)

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
    )
