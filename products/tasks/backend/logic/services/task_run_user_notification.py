"""Let a task's agent notify the task owner in Slack, and let the owner remote control the task from there.

The recipient is always the task's creator. The agent picks the words, never the person, so a
prompt-injected agent can at most message the owner of its own task.

A plain notification is a DM. With remote control on, the DM opens a thread that is bound to the run,
the same binding a Slack-started task gets: a reply in the thread reaches the task, and the agent's
answers post into it. Messages the owner sends from PostHog Code are mirrored into the thread, and the
binding moves to each new run of the task, so the owner can continue from either place.

A DM thread on a task that did not start in Slack can only come from this module, which is how
``is_remote_control_thread`` tells remote control from a Slack-started conversation without a marker column.
"""

from uuid import UUID

from django.conf import settings

import structlog

from posthog.dataclasses import frozen
from posthog.models.integration import Integration, SlackIntegration
from posthog.models.user import User
from posthog.slack.formatting import escape_slack_mrkdwn

from products.slack_app.backend.facade.api import SlackDmRecipient, resolve_slack_dm_recipient
from products.slack_app.backend.feature_flags import is_slack_app_assistant_enabled, is_slack_app_oauth_enabled
from products.slack_app.backend.models import SlackThreadTaskMapping
from products.slack_app.backend.services.slack_messages import post_slack_thread_reply
from products.tasks.backend.facade.contracts import (
    UserNotificationChannel,
    UserNotificationOutcome,
    UserNotificationReason,
    UserNotificationResultDTO,
)
from products.tasks.backend.logic.services.run_actor import user_has_current_team_access
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.redis import get_tasks_cache

logger = structlog.get_logger(__name__)

COOLDOWN_SECONDS = 30
# Slack rejects a section longer than 3000 characters.
_BODY_LIMIT = 2900
_ACCENT = "good"
_IM = SlackThreadTaskMapping.ConversationType.IM

_HEADINGS: dict[UserNotificationReason, str] = {
    UserNotificationReason.UPDATE: "Update on {link}",
    UserNotificationReason.NEEDS_INPUT: "{link} needs your input",
    UserNotificationReason.DONE: "{link} is done",
}
_REMOTE_CONTROL_ON = (
    "Remote control is on. Reply in this thread to talk to the agent. Messages from PostHog Code show here too."
)
_REMOTE_CONTROL_OFF = "Remote control is off. Use PostHog Code to talk to the agent."


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
    remote_control: bool | None = None,
) -> UserNotificationResultDTO:
    """``remote_control``: True turns it on or keeps it on, False turns it off, None keeps the current state."""
    task = task_run.task
    owner = task.created_by
    delivery: _Delivery
    if owner is None or not user_has_current_team_access(owner, task.team):
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
            delivery = _notify_on_slack(
                task_run=task_run, owner=owner, reason=reason, message=message, remote_control=remote_control
            )
            if delivery.result.result != UserNotificationOutcome.SENT:
                # Only a delivered notification starts the cooldown, so a retry after a fix goes out.
                cache.delete(cooldown_key)

    task_run.capture_event(
        "task_run_user_notified",
        {
            "notification_channel": channel.value,
            "notification_reason": reason.value,
            "remote_control": remote_control,
            "outcome": delivery.result.result.value,
            "skip_reason": delivery.skip_reason,
            "remote_control_active": delivery.result.remote_control_active,
        },
    )
    return delivery.result


def is_remote_control_thread(mapping: SlackThreadTaskMapping, task: Task) -> bool:
    return mapping.conversation_type == _IM and task.origin_product != Task.OriginProduct.SLACK


def move_remote_control_to_run(*, task: Task, task_run: TaskRun) -> bool:
    """Point the task's remote control thread at a new run, so replies and answers follow the newest run.

    Call it inside the transaction that creates the run. A reply that arrives a moment later then
    reaches the new run instead of resuming an old one next to it.
    """
    if task.origin_product == Task.OriginProduct.SLACK:
        return False
    moved = (
        SlackThreadTaskMapping.objects.filter(task_id=task.id, conversation_type=_IM)
        .exclude(task_run_id=task_run.id)
        .update(task_run=task_run)
    )
    return moved > 0


def mirror_user_message_to_slack(*, team_id: int, task_run_id: str, actor_user_id: int | None, content: str) -> None:
    """Post a message the user sent from PostHog Code into the run's remote control thread, if it has one."""
    if not content.strip():
        return
    mapping = (
        SlackThreadTaskMapping.objects.filter(team_id=team_id, task_run_id=UUID(task_run_id), conversation_type=_IM)
        .select_related("integration", "task")
        .first()
    )
    if mapping is None or not is_remote_control_thread(mapping, mapping.task):
        return
    actor = User.objects.filter(id=actor_user_id).only("first_name", "last_name", "email").first()
    name = (actor and (f"{actor.first_name} {actor.last_name}".strip() or actor.email)) or "Someone"
    try:
        post_slack_thread_reply(
            SlackIntegration(mapping.integration).client,
            channel=mapping.channel,
            thread_ts=mapping.thread_ts,
            text=f"*{escape_slack_mrkdwn(name)}* in PostHog Code:\n{_truncate_body(content)}",
            unfurl_links=False,
            unfurl_media=False,
        )
    except Exception as exc:
        logger.warning("task_run_slack_mirror_post_failed", task_run_id=task_run_id, error=str(exc))


def _notify_on_slack(
    *,
    task_run: TaskRun,
    owner: User,
    reason: UserNotificationReason,
    message: str,
    remote_control: bool | None,
) -> _Delivery:
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

    task = task_run.task
    run_mappings = list(SlackThreadTaskMapping.objects.filter(task_run=task_run))
    thread = next((mapping for mapping in run_mappings if _is_owner_dm(mapping, recipient)), None)

    if thread is None and remote_control:
        # The relay posts each answer to one thread per run, so a run that a Slack channel thread drives
        # keeps that thread.
        if run_mappings:
            return _not_sent(
                "This task already continues in a Slack channel thread. Replies there reach you.", "channel_thread"
            )
        if not is_slack_app_assistant_enabled(recipient.integration):
            return _not_sent(
                "The PostHog Slack app cannot read DM replies in this workspace, so remote control cannot start. "
                "Send the message without remote_control.",
                "missing_dm_scopes",
            )
        thread = _earlier_owner_dm_thread(task=task, recipient=recipient)
        if thread is not None:
            thread.task_run = task_run
            thread.save(update_fields=["task_run", "updated_at"])

    stops = thread is not None and remote_control is False and is_remote_control_thread(thread, task)
    opens = thread is None and bool(remote_control)
    heading, blocks = _message(
        task=task,
        reason=reason,
        message=message,
        # A thread reply only notifies people who follow the thread, and a mention makes the owner one.
        mention=recipient.slack_user_id if thread is not None else None,
        footer=_REMOTE_CONTROL_ON if opens else _REMOTE_CONTROL_OFF if stops else None,
    )
    try:
        response = post_slack_thread_reply(
            recipient.slack.client,
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
    if response is None:
        return _not_sent(
            "The Slack thread for this task is gone. Send the message without remote_control.",
            "slack_thread_missing",
        )

    if stops and thread is not None:
        thread.delete()
        return _sent(remote_control_active=False)
    if thread is not None:
        return _sent(remote_control_active=True)
    if not opens:
        return _sent(remote_control_active=False)
    return _sent(
        remote_control_active=_bind_dm_thread(
            task_run=task_run,
            recipient=recipient,
            channel=str(response.get("channel") or ""),
            thread_ts=str(response.get("ts") or ""),
        )
    )


def _is_owner_dm(mapping: SlackThreadTaskMapping, recipient: SlackDmRecipient) -> bool:
    return (
        mapping.integration_id == recipient.integration.id
        and mapping.conversation_type == _IM
        and mapping.mentioning_slack_user_id == recipient.slack_user_id
    )


def _earlier_owner_dm_thread(*, task: Task, recipient: SlackDmRecipient) -> SlackThreadTaskMapping | None:
    """A DM thread of this task from an earlier run, so the owner keeps one conversation per task."""
    return (
        SlackThreadTaskMapping.objects.filter(
            task_id=task.id,
            integration=recipient.integration,
            conversation_type=_IM,
            mentioning_slack_user_id=recipient.slack_user_id,
        )
        .order_by("-created_at")
        .first()
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
            conversation_type=_IM,
        )
    except Exception:
        logger.exception("task_run_user_notification_bind_failed", task_run_id=str(task_run.id))
        return False
    return True


def _message(
    *, task: Task, reason: UserNotificationReason, message: str, mention: str | None, footer: str | None
) -> tuple[str, list[dict]]:
    # A pipe in the title would end the link label early, so it can't survive into the label.
    label = escape_slack_mrkdwn(task.title or "Your task").replace("|", "-")
    heading = _HEADINGS[reason].format(link=f"<{settings.SITE_URL}/code/task/{task.id}|{label}>")
    if mention:
        heading = f"<@{mention}> {heading}"
    blocks: list[dict] = [{"type": "section", "text": {"type": "mrkdwn", "text": _truncate_body(message)}}]
    if footer:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": footer}]})
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


def _sent(*, remote_control_active: bool) -> _Delivery:
    detail = "The task owner got a Slack DM."
    if remote_control_active:
        detail += " Remote control is on: replies in that DM thread reach you, and your answers post there."
    return _Delivery(
        result=UserNotificationResultDTO(
            result=UserNotificationOutcome.SENT, detail=detail, remote_control_active=remote_control_active
        )
    )


def _not_sent(detail: str, skip_reason: str) -> _Delivery:
    return _Delivery(
        result=UserNotificationResultDTO(result=UserNotificationOutcome.NOT_SENT, detail=detail),
        skip_reason=skip_reason,
    )
