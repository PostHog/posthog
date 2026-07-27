"""Fan out a loop lifecycle event to every channel configured on the loop.

Modeled on push_dispatcher.py: every channel send is independently wrapped so
a failure in one (a downed Slack workspace, an SMTP outage) never blocks the
others, and nothing here ever raises into the caller. Safe to call from
Celery task and Temporal activity contexts alike, no request assumed.

``payload`` carries event-specific detail from the caller. Recognized keys
(all optional): ``title`` / ``body`` override the generated copy, ``url``
links to the run or PR, ``task_id`` / ``task_run_id`` identify the run for
push deep-linking and email idempotency.
"""

from typing import Any

from django.db import transaction

import structlog
from slack_sdk.errors import SlackApiError

from posthog.email import EmailMessage, is_email_available
from posthog.models.integration import Integration, SlackIntegration
from posthog.redis import get_client
from posthog.tasks.push_notifications import send_user_push

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    TargetType,
    create_notification,
)
from products.tasks.backend.models import Loop

logger = structlog.get_logger(__name__)

PUSH_TITLE = "PostHog Code"

_COOLDOWN_EVENTS = frozenset({"run_failed", "needs_attention"})
_COOLDOWN_TTL_SECONDS = 300

_PERMANENT_SLACK_ERRORS = frozenset({"channel_not_found", "is_archived", "account_inactive"})
_SLACK_BODY_MAX_CHARS = 3000

# (event copy suffix, default body) for events without an explicit payload override.
_EVENT_DEFAULTS: dict[str, tuple[str, str]] = {
    "run_completed": ("finished", "The run finished successfully."),
    "run_failed": ("failed", "The run failed. Check the run for details."),
    "pr_created": ("opened a PR", "A new pull request was opened."),
    "needs_attention": ("needs attention", "This loop needs your attention."),
}


def dispatch_loop_event(loop: Loop, event: str, payload: dict[str, Any]) -> None:
    title, body = _event_copy(loop, event, payload)

    # In-app sits behind the cooldown too: failure/attention events can repeat every fire (a
    # capped or crash-looping loop), and each in-app send is a new notification row.
    if not _acquire_cooldown(loop, event):
        logger.info("loop_notifications.cooldown_dropped", loop_id=str(loop.id), loop_event=event)
        return

    _send_in_app(loop, event, title, body, payload)

    config = loop.notifications if isinstance(loop.notifications, dict) else {}
    _send_push(loop, event, title, payload, config.get("push") or {})
    _send_email(loop, event, title, body, payload, config.get("email") or {})
    _send_slack(loop, event, title, body, config.get("slack") or {})


def _event_copy(loop: Loop, event: str, payload: dict[str, Any]) -> tuple[str, str]:
    suffix, default_body = _EVENT_DEFAULTS.get(event, (event, ""))
    override_title = payload.get("title")
    override_body = payload.get("body")
    title = str(override_title) if override_title else f'Loop "{loop.name}" {suffix}'
    body = str(override_body) if override_body else default_body
    return title, body


def _channel_enabled(channel_config: dict[str, Any], event: str) -> bool:
    if not channel_config.get("enabled"):
        return False
    return event in (channel_config.get("events") or [])


def _acquire_cooldown(loop: Loop, event: str) -> bool:
    if event not in _COOLDOWN_EVENTS:
        return True
    try:
        client = get_client()
        key = f"loop_notifications:cooldown:{loop.id}:{event}"
        return bool(client.set(key, "1", nx=True, ex=_COOLDOWN_TTL_SECONDS))
    except Exception:
        # Fail open: a Redis outage must not silently swallow a failure/attention notification.
        logger.warning(
            "loop_notifications.cooldown_check_failed", loop_id=str(loop.id), loop_event=event, exc_info=True
        )
        return True


def _notification_type_for(event: str) -> NotificationType:
    if event in {"run_failed", "needs_attention"}:
        return NotificationType.PIPELINE_FAILURE
    return NotificationType.REMINDER


def _priority_for(event: str) -> Priority:
    return Priority.CRITICAL if event in {"run_failed", "needs_attention"} else Priority.NORMAL


def _send_in_app(loop: Loop, event: str, title: str, body: str, payload: dict[str, Any]) -> None:
    if loop.created_by_id is None:
        return
    try:
        create_notification(
            NotificationData(
                team_id=loop.team_id,
                notification_type=_notification_type_for(event),
                priority=_priority_for(event),
                title=title[:100],
                body=body[:200],
                target_type=TargetType.USER,
                target_id=str(loop.created_by_id),
                resource_type="loop",
                resource_id=str(loop.id),
                source_url=str(payload.get("url") or ""),
            )
        )
    except Exception:
        logger.warning("loop_notifications.in_app_failed", loop_id=str(loop.id), loop_event=event, exc_info=True)


def _send_push(loop: Loop, event: str, title: str, payload: dict[str, Any], channel_config: dict[str, Any]) -> None:
    if not _channel_enabled(channel_config, event) or loop.created_by_id is None:
        return
    try:
        data: dict[str, Any] = {"loopId": str(loop.id), "event": event}
        if payload.get("task_id"):
            data["taskId"] = str(payload["task_id"])
        if payload.get("task_run_id"):
            data["taskRunId"] = str(payload["task_run_id"])
        user_id = loop.created_by_id
        transaction.on_commit(lambda: send_user_push.delay(user_id, PUSH_TITLE, title, data))
    except Exception:
        logger.warning("loop_notifications.push_failed", loop_id=str(loop.id), loop_event=event, exc_info=True)


def _send_email(
    loop: Loop, event: str, title: str, body: str, payload: dict[str, Any], channel_config: dict[str, Any]
) -> None:
    if not _channel_enabled(channel_config, event) or loop.created_by is None:
        return
    if not is_email_available():
        return
    try:
        campaign_key = f"loop_run_summary:{loop.id}:{payload.get('task_run_id') or payload.get('fire_key') or event}"
        template_context = {
            "loop_name": loop.name,
            "event_title": title,
            "event_body": body,
            "run_url": str(payload.get("url") or ""),
        }
        message = EmailMessage(
            campaign_key=campaign_key,
            template_name="loop_run_summary",
            subject=title,
            template_context=template_context,
            use_http=True,
        )
        message.add_user_recipient(loop.created_by)
        message.send(send_async=True)
    except Exception:
        logger.warning("loop_notifications.email_failed", loop_id=str(loop.id), loop_event=event, exc_info=True)


def _send_slack(loop: Loop, event: str, title: str, body: str, channel_config: dict[str, Any]) -> None:
    if not _channel_enabled(channel_config, event):
        return
    params = channel_config.get("params") or {}
    integration_id = params.get("integration_id")
    channel = params.get("channel")
    if not integration_id or not channel:
        return
    try:
        integration = Integration.objects.filter(id=integration_id, team_id=loop.team_id, kind="slack").first()
        if integration is None:
            logger.warning(
                "loop_notifications.slack_integration_missing", loop_id=str(loop.id), integration_id=integration_id
            )
            return
        text = _truncate(f"*{title}*\n{body}", _SLACK_BODY_MAX_CHARS)
        SlackIntegration(integration).client.chat_postMessage(
            channel=channel, text=text, unfurl_links=False, unfurl_media=False
        )
    except SlackApiError as e:
        error_code = e.response.get("error") if e.response else None
        if error_code in _PERMANENT_SLACK_ERRORS:
            _disable_slack_channel(loop, error_code)
        else:
            logger.warning(
                "loop_notifications.slack_transient_error",
                loop_id=str(loop.id),
                loop_event=event,
                error=error_code,
                exc_info=True,
            )
    except Exception:
        logger.warning("loop_notifications.slack_failed", loop_id=str(loop.id), loop_event=event, exc_info=True)


def _disable_slack_channel(loop: Loop, error_code: str | None) -> None:
    notifications = dict(loop.notifications) if isinstance(loop.notifications, dict) else {}
    slack_config = dict(notifications.get("slack") or {})
    slack_config["enabled"] = False
    notifications["slack"] = slack_config
    loop.notifications = notifications
    loop.save(update_fields=["notifications", "updated_at"])

    if loop.created_by_id is None:
        return
    try:
        create_notification(
            NotificationData(
                team_id=loop.team_id,
                notification_type=NotificationType.PIPELINE_FAILURE,
                priority=Priority.NORMAL,
                title=f'Slack notifications disabled for loop "{loop.name}"'[:100],
                body=(
                    f"PostHog could no longer post to the configured Slack channel ({error_code}) "
                    "and disabled Slack notifications for this loop."
                )[:200],
                target_type=TargetType.USER,
                target_id=str(loop.created_by_id),
                resource_type="loop",
                resource_id=str(loop.id),
            )
        )
    except Exception:
        logger.warning("loop_notifications.slack_disable_notify_failed", loop_id=str(loop.id), exc_info=True)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
