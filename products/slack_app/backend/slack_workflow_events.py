"""Forward Slack channel messages and reactions onto the internal events topic.

Deliberately dumb: check Slack is telling us about a new post or reaction, resolve the PostHog
projects behind the Slack workspace, then write the event out as-is. A workflow's trigger config
decides what it wants, and the CDP consumer evaluates that, so nothing here needs to know a trigger
exists.
"""

import uuid
from typing import Any, Protocol

from django.conf import settings

import structlog

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event
from posthog.models.integration import Integration

logger = structlog.get_logger(__name__)

SLACK_MESSAGE_RECEIVED_EVENT = "$slack_message_received"
SLACK_REACTION_ADDED_EVENT = "$slack_reaction_added"

# Slack labels edits, deletions and joins `message` too, and those retrigger a workflow's own reply.
# `bot_message` stays in: "apps and bots only" is a trigger mode.
_TRIGGERING_SUBTYPES: frozenset[str | None] = frozenset(
    {None, "bot_message", "file_share", "me_message", "thread_broadcast"}
)

# Reactions land on files and file comments too. Only a message carries the thread coordinates a
# workflow needs to answer where the reaction happened, so the rest are dropped at the door.
_REACTION_ITEM_TYPE = "message"

# Fixed namespace so the event uuid is a pure function of (team, Slack event id). Slack redelivers
# on any non-2xx, and the handler's retry guard only covers the copies that carry the retry header.
_SLACK_EVENT_NAMESPACE = uuid.UUID("6f1a4b3c-0d2e-4f6a-9b5c-8e7d1a2f3b4c")


class _PropertiesBuilder(Protocol):
    def __call__(
        self, event: dict[str, Any], slack_team_id: str, *, integration_id: int, is_ext_shared_channel: bool
    ) -> dict[str, Any]: ...


def _event_properties(
    event: dict[str, Any], slack_team_id: str, *, integration_id: int, is_ext_shared_channel: bool
) -> dict[str, Any]:
    thread_ts = event.get("thread_ts")
    return {
        # The PostHog Slack connection this copy belongs to. The CDP consumer reads its stored
        # app id from here to recognize, and ignore, a message PostHog itself posted.
        "integration_id": integration_id,
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


def _reaction_item(event: dict[str, Any]) -> dict[str, Any]:
    """The thing that was reacted to, or an empty dict when Slack sent something unexpected."""
    item = event.get("item")
    return item if isinstance(item, dict) else {}


def reaction_name(raw: Any) -> str:
    """The emoji's base name, with any skin tone dropped.

    Slack sends `+1::skin-tone-3` when the person who reacted has a default tone set. A filter
    stores the emoji someone picked, so matching on the raw value silently ignores every teammate
    whose tone differs from theirs. The full value stays on `slack_event` for anyone who needs it.
    """
    return str(raw or "").split("::", 1)[0]


def _reaction_properties(
    event: dict[str, Any], slack_team_id: str, *, integration_id: int, is_ext_shared_channel: bool
) -> dict[str, Any]:
    item = _reaction_item(event)
    return {
        # The PostHog Slack connection this copy belongs to. The CDP consumer reads its stored bot
        # user id from here to recognize, and ignore, a reaction PostHog itself added.
        "integration_id": integration_id,
        # Flat, and under the same key a message uses, so one channel picker serves both triggers.
        # Slack files a reaction's channel under `item`, not beside `user` like a message does.
        "channel": item.get("channel"),
        "slack_team_id": slack_team_id,
        "reaction": reaction_name(event.get("reaction")),
        # `user` reacted; `item_user` wrote the message they reacted to. Naming the reactor `user`
        # keeps "who can start a run" the same filter on both triggers.
        "user": event.get("user"),
        "item_user": event.get("item_user"),
        "item_type": item.get("type"),
        "item_ts": item.get("ts"),
        "is_ext_shared_channel": is_ext_shared_channel,
        "slack_event": event,
    }


def is_triggering_message(event: dict[str, Any]) -> bool:
    """Whether a workflow trigger could fire on this message, and the emit would write it out.

    Exposed so the webhook can decide about a cross-region mirror without spending a probe or a
    hop on the subtypes (edits, joins, deletions) no trigger fires on.
    """
    return bool(settings.SLACK_WORKFLOW_TRIGGERS_ENABLED) and event.get("subtype") in _TRIGGERING_SUBTYPES


def is_triggering_reaction(event: dict[str, Any]) -> bool:
    """Whether a workflow trigger could fire on this reaction, and the emit would write it out.

    The webhook asks before spending a probe or a hop, same as `is_triggering_message`.
    """
    if not settings.SLACK_WORKFLOW_TRIGGERS_ENABLED:
        return False
    item = event.get("item")
    return isinstance(item, dict) and item.get("type") == _REACTION_ITEM_TYPE and bool(item.get("ts"))


def emit_slack_message_event(
    event: dict[str, Any],
    slack_team_id: str,
    *,
    event_id: str | None,
    is_ext_shared_channel: bool,
) -> bool:
    """Write one internal event per PostHog project connected to this Slack workspace.

    Returns whether the event still needs a home: True only when a workflow could have triggered on
    it and no connection in this region holds the workspace. The caller turns that into a
    cross-region hand-off. Every other outcome is False, including the cases where there was nothing
    to emit at all, so a disabled setting or an edit never costs a hop.

    Never raises. This runs inside the Slack event webhook, which owes Slack an ack within three
    seconds and shares the handler with mention routing, so a failure here has to cost neither.
    """
    if not is_triggering_message(event):
        return False
    return _emit(
        event,
        slack_team_id,
        event_name=SLACK_MESSAGE_RECEIVED_EVENT,
        build_properties=_event_properties,
        distinct_id=str(event.get("user") or event.get("bot_id") or event.get("channel") or slack_team_id),
        event_id=event_id,
        is_ext_shared_channel=is_ext_shared_channel,
    )


def emit_slack_reaction_event(
    event: dict[str, Any],
    slack_team_id: str,
    *,
    event_id: str | None,
    is_ext_shared_channel: bool,
) -> bool:
    """Write one internal event per PostHog project connected to this Slack workspace.

    Same contract as `emit_slack_message_event`, including the cross-region return and the promise
    never to raise inside the webhook.
    """
    if not is_triggering_reaction(event):
        return False
    item = _reaction_item(event)
    return _emit(
        event,
        slack_team_id,
        event_name=SLACK_REACTION_ADDED_EVENT,
        build_properties=_reaction_properties,
        distinct_id=str(event.get("user") or item.get("channel") or slack_team_id),
        event_id=event_id,
        is_ext_shared_channel=is_ext_shared_channel,
    )


def _emit(
    event: dict[str, Any],
    slack_team_id: str,
    *,
    event_name: str,
    build_properties: _PropertiesBuilder,
    distinct_id: str,
    event_id: str | None,
    is_ext_shared_channel: bool,
) -> bool:
    try:
        # A Slack workspace can be connected to several projects (the unique constraint on
        # Integration is per team), and each configures its own workflows, so every one gets a copy.
        # Projects with nothing listening are discarded by the CDP consumer, which is cheaper than
        # asking Postgres here.
        integrations = list(
            Integration.objects.filter(kind="slack", integration_id=slack_team_id).values_list("team_id", "id")
        )
    except Exception:
        # Stay put on a lookup failure: handing the workspace over would turn a local database blip
        # into a cross-region hop for every message in every channel.
        logger.exception("slack_workflow_event_integration_lookup_failed", slack_team_id=slack_team_id)
        return False

    for team_id, integration_id in integrations:
        try:
            produce_internal_event(
                team_id,
                InternalEventEvent(
                    event=event_name,
                    distinct_id=distinct_id,
                    properties=build_properties(
                        event,
                        slack_team_id,
                        integration_id=integration_id,
                        is_ext_shared_channel=is_ext_shared_channel,
                    ),
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

    return not integrations
