"""Forward Slack channel messages onto the internal events topic.

Deliberately dumb: resolve the PostHog projects behind the Slack workspace, then write the message
out as-is. No matching, no gating, no filtering. A workflow's trigger config decides what it wants,
and the CDP consumer evaluates that, so nothing here needs to know a trigger exists.
"""

import uuid
from typing import Any

from django.conf import settings

import structlog

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event
from posthog.models.integration import Integration

logger = structlog.get_logger(__name__)

SLACK_MESSAGE_RECEIVED_EVENT = "$slack_message_received"

# Fixed namespace so the event uuid is a pure function of (team, Slack event id). Slack redelivers
# on any non-2xx, and the handler's retry guard only covers the copies that carry the retry header.
_SLACK_EVENT_NAMESPACE = uuid.UUID("6f1a4b3c-0d2e-4f6a-9b5c-8e7d1a2f3b4c")


def _event_properties(event: dict[str, Any], slack_team_id: str, *, is_ext_shared_channel: bool) -> dict[str, Any]:
    thread_ts = event.get("thread_ts")
    return {
        "channel": event.get("channel"),
        "channel_type": event.get("channel_type"),
        "slack_team_id": slack_team_id,
        "user": event.get("user"),
        "bot_id": event.get("bot_id"),
        "app_id": event.get("app_id"),
        "subtype": event.get("subtype"),
        "text": event.get("text"),
        "ts": event.get("ts"),
        "thread_ts": thread_ts,
        # Property filters compare a property against a constant, never against another property,
        # so "is this a reply" is unexpressible from thread_ts and ts alone.
        "is_thread_reply": isinstance(thread_ts, str) and thread_ts != event.get("ts"),
        "is_ext_shared_channel": is_ext_shared_channel,
        # Anything a step wants that the flat fields above don't cover, blocks and attachments most
        # of all: an alerting app posts Block Kit, so its text is often empty.
        "slack_event": event,
    }


def emit_slack_message_event(
    event: dict[str, Any],
    slack_team_id: str,
    *,
    event_id: str | None,
    is_ext_shared_channel: bool,
) -> None:
    """Write one internal event per PostHog project connected to this Slack workspace.

    Never raises. This runs inside the Slack event webhook, which owes Slack an ack within three
    seconds and shares the handler with mention routing, so a failure here has to cost neither.
    """
    if not settings.SLACK_WORKFLOW_TRIGGERS_ENABLED:
        return

    try:
        # A Slack workspace can be connected to several projects (the unique constraint on
        # Integration is per team), and each configures its own workflows, so every one gets a copy.
        # Projects with nothing listening are discarded by the CDP consumer, which is cheaper than
        # asking Postgres here.
        team_ids = list(
            Integration.objects.filter(kind="slack", integration_id=slack_team_id).values_list("team_id", flat=True)
        )
    except Exception:
        logger.exception("slack_workflow_event_integration_lookup_failed", slack_team_id=slack_team_id)
        return

    properties = _event_properties(event, slack_team_id, is_ext_shared_channel=is_ext_shared_channel)
    distinct_id = str(event.get("user") or event.get("bot_id") or event.get("channel") or slack_team_id)

    for team_id in team_ids:
        try:
            produce_internal_event(
                team_id,
                InternalEventEvent(
                    event=SLACK_MESSAGE_RECEIVED_EVENT,
                    distinct_id=distinct_id,
                    properties=properties,
                    uuid=str(uuid.uuid5(_SLACK_EVENT_NAMESPACE, f"{team_id}:{event_id or ''}")),
                ),
            )
        except Exception:
            # Deliberately not flushed or waited on — the delivery callback runs in the background,
            # and blocking here would spend the Slack ack budget on Kafka.
            logger.exception(
                "slack_workflow_event_produce_failed",
                slack_team_id=slack_team_id,
                team_id=team_id,
                event_id=event_id,
            )
