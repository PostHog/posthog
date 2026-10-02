"""Let a task's agent notify the task owner outside PostHog Code.

The recipient is always the task's creator. The agent picks the channel and the words, never the
person, so a prompt-injected agent can at most message the owner of its own task.

On Slack, the first notification opens a DM thread bound to the run, the same binding a Slack-started
task gets: a reply in the thread continues the task, and the agent's answers post back into it. Later
notifications for the task reply in that thread, so one task keeps one conversation.
"""

from django.conf import settings

import structlog

from posthog.dataclasses import frozen
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.user import User
from posthog.slack.formatting import escape_slack_mrkdwn
from posthog.user_permissions import UserPermissions

from products.slack_app.backend.feature_flags import is_slack_app_assistant_enabled, is_slack_app_oauth_enabled
from products.slack_app.backend.models import SlackThreadTaskMapping
from products.tasks.backend.facade.contracts import (
    UserNotificationChannel,
    UserNotificationOutcome,
    UserNotificationReason,
    UserNotificationResultDTO,
)
from products.tasks.backend.logic.services.slack_dm_recipient import SlackDmRecipient, resolve_slack_dm_recipient
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.redis import get_tasks_cache

logger = structlog.get_logger(__name__)

COOLDOWN_SECONDS = 30
# Slack rejects a section longer than 3000 characters.
_BODY_LIMIT = 2900
_ACCENT = "good"

_HEADINGS: dict[UserNotificationReason, str] = {
    UserNotificationReason.UPDATE: "Update on {link}",
    UserNotificationReason.NEEDS_INPUT: "{link} needs your input",
    UserNotificationReason.DONE: "{link} is done",
}


@frozen
class _Delivery:
    result: UserNotificationResultDTO
    skip_reason: str | None = None


def notify_task_owner(
    *,
    task_run: TaskRun,
    channel: UserNotificationChannel,
    reason: UserNotificationReason,
    message: str,
) -> UserNotificationResultDTO:
    task = task_run.task
    owner = task.created_by
    delivery: _Delivery
    if owner is None or not owner.is_active or not _owner_can_open_task(task=task, owner=owner):
        delivery = _not_sent("This task has no owner who can receive notifications.", "owner_unavailable")
    else:
        cooldown_key = f"task_run_notify_user:{task_run.id}"
        cache = get_tasks_cache()
        if not cache.add(cooldown_key, True, timeout=COOLDOWN_SECONDS):
            delivery = _Delivery(
                result=UserNotificationResultDTO(
                    result=UserNotificationOutcome.THROTTLED,
                    detail=(
                        f"You sent a notification less than {COOLDOWN_SECONDS} seconds ago. "
                        "Wait, then send one message that covers everything."
                    ),
                ),
                skip_reason="cooldown",
            )
        else:
            delivery = _notify_on_slack(task_run=task_run, owner=owner, reason=reason, message=message)
            if delivery.result.result != UserNotificationOutcome.SENT:
                # Only a delivered notification starts the cooldown, so a retry after a fix goes out.
                cache.delete(cooldown_key)

    task_run.capture_event(
        "task_run_user_notified",
        {
            "notification_channel": channel.value,
            "notification_reason": reason.value,
            "outcome": delivery.result.result.value,
            "skip_reason": delivery.skip_reason,
            "replies_continue_task": delivery.result.replies_continue_task,
        },
    )
    return delivery.result


def _owner_can_open_task(*, task: Task, owner: User) -> bool:
    team = task.team
    if not OrganizationMembership.objects.filter(organization_id=team.organization_id, user_id=owner.id).exists():
        return False
    return UserPermissions(user=owner, team=team).current_team.effective_membership_level is not None


def _notify_on_slack(*, task_run: TaskRun, owner: User, reason: UserNotificationReason, message: str) -> _Delivery:
    integrations = [
        integration
        for integration in Integration.objects.filter(team_id=task_run.team_id, kind=Integration.IntegrationKind.SLACK)
        .exclude(integration_id__isnull=True)
        .exclude(integration_id="")
        .order_by("id")
        if settings.DEBUG or is_slack_app_oauth_enabled(integration)
    ]
    if not integrations:
        return _not_sent("Slack is not connected to this project, so PostHog cannot send a Slack message.", "no_slack")
    recipient = resolve_slack_dm_recipient(user=owner, integrations=integrations)
    if recipient is None:
        return _not_sent(
            "PostHog could not find the task owner in Slack. They can link their Slack account in PostHog.",
            "recipient_not_found_in_slack",
        )

    run_mappings = list(SlackThreadTaskMapping.objects.filter(task_run=task_run))
    thread = _owner_dm_thread(task_run=task_run, recipient=recipient, run_mappings=run_mappings)
    # A run that a Slack channel thread already drives keeps that thread. The relay posts each answer to
    # one thread per run, so a second binding would split the conversation.
    bind_new_thread = thread is None and not run_mappings and is_slack_app_assistant_enabled(recipient.integration)
    heading, blocks = _message(
        task=task_run.task,
        reason=reason,
        message=message,
        # A thread reply only notifies people who follow the thread, and a mention makes the owner one.
        mention=recipient.slack_user_id if thread is not None else None,
        continue_hint=bind_new_thread,
    )
    try:
        response = recipient.slack.client.chat_postMessage(
            channel=thread.channel if thread is not None else recipient.slack_user_id,
            thread_ts=thread.thread_ts if thread is not None else None,
            text=heading,
            attachments=[{"color": _ACCENT, "blocks": blocks}],
            unfurl_links=False,
            unfurl_media=False,
        )
    except Exception as exc:
        logger.warning("task_run_user_notification_slack_failed", task_run_id=str(task_run.id), error=str(exc))
        return _not_sent("Slack did not accept the message. Try again later.", "slack_error")

    if thread is not None:
        if thread.task_run_id != task_run.id:
            thread.task_run = task_run
            thread.save(update_fields=["task_run", "updated_at"])
        return _sent(replies_continue_task=True)
    if not bind_new_thread:
        return _sent(replies_continue_task=False)
    return _sent(
        replies_continue_task=_bind_dm_thread(
            task_run=task_run,
            recipient=recipient,
            channel=str(response.get("channel") or ""),
            thread_ts=str(response.get("ts") or ""),
        )
    )


def _owner_dm_thread(
    *, task_run: TaskRun, recipient: SlackDmRecipient, run_mappings: list[SlackThreadTaskMapping]
) -> SlackThreadTaskMapping | None:
    """The owner's DM thread for this task, when there is one this run may use.

    A run without a thread takes over the task's latest DM thread from an earlier run, so the owner
    keeps one conversation per task. That also covers a task the owner started in a DM to the app.
    """

    def is_owner_dm(mapping: SlackThreadTaskMapping) -> bool:
        return (
            mapping.integration_id == recipient.integration.id
            and mapping.conversation_type == SlackThreadTaskMapping.ConversationType.IM
            and mapping.mentioning_slack_user_id == recipient.slack_user_id
        )

    if run_mappings:
        return next((mapping for mapping in run_mappings if is_owner_dm(mapping)), None)
    return next(
        (
            mapping
            for mapping in SlackThreadTaskMapping.objects.filter(
                task_id=task_run.task_id,
                integration=recipient.integration,
                conversation_type=SlackThreadTaskMapping.ConversationType.IM,
                mentioning_slack_user_id=recipient.slack_user_id,
            ).order_by("-created_at")
        ),
        None,
    )


def _bind_dm_thread(*, task_run: TaskRun, recipient: SlackDmRecipient, channel: str, thread_ts: str) -> bool:
    if not channel or not thread_ts:
        logger.warning("task_run_user_notification_bind_missing_ts", task_run_id=str(task_run.id))
        return False
    try:
        SlackThreadTaskMapping.objects.create(
            team_id=task_run.team_id,
            integration=recipient.integration,
            slack_workspace_id=recipient.integration.integration_id or "",
            channel=channel,
            thread_ts=thread_ts,
            task_id=task_run.task_id,
            task_run=task_run,
            mentioning_slack_user_id=recipient.slack_user_id,
            # The notification itself is not a message for the agent to catch up on.
            last_forwarded_ts=thread_ts,
            conversation_type=SlackThreadTaskMapping.ConversationType.IM,
        )
    except Exception:
        logger.exception("task_run_user_notification_bind_failed", task_run_id=str(task_run.id))
        return False
    return True


def _message(
    *, task: Task, reason: UserNotificationReason, message: str, mention: str | None, continue_hint: bool
) -> tuple[str, list[dict]]:
    # A pipe in the title would end the link label early, so it can't survive into the label.
    label = escape_slack_mrkdwn(task.title or "Your task").replace("|", "-")
    heading = _HEADINGS[reason].format(link=f"<{settings.SITE_URL}/code/task/{task.id}|{label}>")
    if mention:
        heading = f"<@{mention}> {heading}"
    blocks: list[dict] = [{"type": "section", "text": {"type": "mrkdwn", "text": _truncate_body(message)}}]
    if continue_hint:
        blocks.append(
            {"type": "context", "elements": [{"type": "mrkdwn", "text": "Reply in this thread to continue the task."}]}
        )
    return heading, blocks


def _truncate_body(message: str) -> str:
    """Escape first, then cut, and never inside an ``&amp;``-style entity, which Slack would show raw."""
    body = escape_slack_mrkdwn(message.strip())
    if len(body) <= _BODY_LIMIT:
        return body
    cut = body[: _BODY_LIMIT - 1]
    entity_start = cut.rfind("&")
    if entity_start > cut.rfind(";"):
        cut = cut[:entity_start]
    return cut.rstrip() + "…"


def _sent(*, replies_continue_task: bool) -> _Delivery:
    detail = "The task owner got a Slack DM."
    if replies_continue_task:
        detail += " A reply in that DM thread reaches you as a new message."
    return _Delivery(
        result=UserNotificationResultDTO(
            result=UserNotificationOutcome.SENT, detail=detail, replies_continue_task=replies_continue_task
        )
    )


def _not_sent(detail: str, skip_reason: str) -> _Delivery:
    return _Delivery(
        result=UserNotificationResultDTO(result=UserNotificationOutcome.NOT_SENT, detail=detail),
        skip_reason=skip_reason,
    )
