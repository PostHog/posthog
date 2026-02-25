from django.core.cache import cache

import structlog

logger = structlog.get_logger(__name__)


def process_twig_repo_selection(payload: dict) -> None:
    """Process default-repo picker selection from Slack interactivity callback."""
    from posthog.models.integration import Integration, SlackIntegration

    from products.slack_app.backend.api import (
        _decode_picker_context,
        _extract_context_token,
        _get_full_repo_names,
        _set_user_default_repo,
        resolve_slack_user,
    )

    actions = payload.get("actions", [])
    action = next((a for a in actions if a.get("action_id") == "twig_default_repo_select"), None)
    if not action:
        logger.info("twig_default_repo_selection_ignored_non_default_action")
        return

    selected_repo = action.get("selected_option", {}).get("value", "")
    if not selected_repo:
        logger.warning("twig_default_repo_selection_no_value")
        return

    action_ts = action.get("action_ts", "")
    slack_user_id = payload.get("user", {}).get("id", "")
    slack_team_id = payload.get("team", {}).get("id")

    if not slack_team_id:
        logger.warning("twig_repo_selection_missing_slack_team")
        return

    context_token = _extract_context_token(payload)
    if not context_token:
        logger.warning("twig_default_repo_selection_no_token")
        return

    logger.info(
        "twig_default_repo_selection_dispatched",
        context_token=context_token,
        selected_repo=selected_repo,
        slack_user_id=slack_user_id,
    )

    ctx = _decode_picker_context(context_token)
    if not ctx:
        logger.info("twig_default_repo_selection_expired_token", context_token=context_token)
        return

    # Submit dedup
    dedup_key = f"twig_repo_select_submit:{context_token}:{action_ts}"
    if not cache.add(dedup_key, True, timeout=300):
        logger.info("twig_default_repo_selection_dedup", context_token=context_token)
        return

    # One-time consume
    used_key = f"twig_repo_picker_used:{context_token}"
    if not cache.add(used_key, True, timeout=900):
        logger.info("twig_default_repo_selection_already_used", context_token=context_token)
        return

    if slack_user_id != ctx["mentioning_slack_user_id"]:
        logger.warning(
            "twig_default_repo_selection_user_mismatch",
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
        logger.warning("twig_default_repo_selection_no_integration", integration_id=ctx["integration_id"])
        return

    all_repos = _get_full_repo_names(integration)
    if selected_repo not in all_repos:
        logger.warning("twig_default_repo_selection_invalid_repo", repo=selected_repo)
        return

    slack = SlackIntegration(integration)
    channel = ctx["channel"]
    thread_ts = ctx["thread_ts"]

    user_context = resolve_slack_user(slack, integration, slack_user_id, channel, thread_ts)
    if not user_context:
        return

    # Update the picker message to show the selection
    picker_message_ts = payload.get("message", {}).get("ts")
    if picker_message_ts:
        try:
            selected_text = f"Set default repository: `{selected_repo}`"
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
            logger.warning("twig_default_repo_selection_update_failed", channel=channel)

    _set_user_default_repo(integration.team_id, user_context.user.id, channel, selected_repo)
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


def process_twig_task_termination(payload: dict) -> None:
    """Backwards-compatible wrapper for terminate handling."""
    from posthog.temporal.ai.twig_slack_interactivity import process_twig_task_termination_payload

    process_twig_task_termination_payload(payload)
