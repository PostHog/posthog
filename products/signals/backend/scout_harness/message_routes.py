"""Owner-set message routes on a scout config, read from `output_destinations.messages`.

A route names who a scout may interrupt and when. The scout picks a route by `key` and never names a
recipient, because a scout reads untrusted text (pull request bodies, tickets) and a free target would
let injected text message anyone. This module only reads the stored config, so the serializers, the
prompt, the tool and the end-of-run send all agree on one parse.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from django.db import connection

import posthoganalytics

from posthog.dataclasses import frozen
from posthog.slack.formatting import channel_id_from_target

if TYPE_CHECKING:
    from posthog.models.team.team import Team

logger = logging.getLogger(__name__)

SCOUT_SEND_MESSAGE_FLAG = "scout-send-message"

MAX_MESSAGE_ROUTES = 10
MAX_ROUTE_TARGETS = 5
MAX_ROUTE_KEY_LENGTH = 64
MAX_ROUTE_WHEN_LENGTH = 300
ROUTE_KEY_RE = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
SLACK_CHANNEL_TARGET_RE = r"^[CG][A-Z0-9]{4,}\s*(\|.*)?$"

# A message is a few sentences that point at a report, so the limits hold it to that rather than to a summary.
MAX_MESSAGE_TITLE_LENGTH = 80
MAX_MESSAGE_BODY_LENGTH = 500

MAX_MESSAGES_PER_SCOUT_PER_WINDOW = 5
MESSAGE_CAP_WINDOW = timedelta(hours=24)
DEDUPE_WINDOW = timedelta(days=30)
# How long a message a failed send left behind is still worth sending. Recovery runs at the scout's next
# run end, so the window must be longer than the default daily schedule or a daily scout recovers nothing.
MESSAGE_RECOVERY_WINDOW = timedelta(days=3)

# A report the inbox does not show: the safety judge suppressed it, a person deleted it, or it failed.
UNSENDABLE_REPORT_STATUSES = frozenset(("deleted", "suppressed", "failed"))

MESSAGE_TARGET_SLACK_DM = "slack_dm"
MESSAGE_TARGET_SLACK_CHANNEL = "slack_channel"


@frozen
class MessageTarget:
    type: str
    # The Slack member or channel id, without the picker's `|name` suffix.
    target_id: str


@frozen
class MessageRoute:
    key: str
    when: str
    targets: tuple[MessageTarget, ...]


def get_message_routes(output_destinations: object) -> tuple[MessageRoute, ...]:
    """The routes stored on a config. Malformed entries are skipped rather than failing the run,
    because rows can predate a validation rule."""
    if not isinstance(output_destinations, dict):
        return ()
    raw_routes = output_destinations.get("messages")
    if not isinstance(raw_routes, list):
        return ()
    routes: list[MessageRoute] = []
    seen_keys: set[str] = set()
    for raw in raw_routes[:MAX_MESSAGE_ROUTES]:
        if not isinstance(raw, dict):
            continue
        key = raw.get("key")
        when = raw.get("when")
        if not isinstance(key, str) or not key or key in seen_keys or not isinstance(when, str):
            continue
        targets = _parse_targets(raw.get("to"))
        if not targets:
            continue
        seen_keys.add(key)
        routes.append(MessageRoute(key=key, when=" ".join(when.split()), targets=targets))
    return tuple(routes)


def _parse_targets(raw_targets: object) -> tuple[MessageTarget, ...]:
    if not isinstance(raw_targets, list):
        return ()
    targets: list[MessageTarget] = []
    for raw in raw_targets[:MAX_ROUTE_TARGETS]:
        if not isinstance(raw, dict):
            continue
        target_type = raw.get("type")
        if target_type == MESSAGE_TARGET_SLACK_DM:
            value = raw.get("user")
            prefixes: tuple[str, ...] = ("U", "W")
        elif target_type == MESSAGE_TARGET_SLACK_CHANNEL:
            value = raw.get("channel")
            prefixes = ("C", "G")
        else:
            continue
        if not isinstance(value, str):
            continue
        target_id = channel_id_from_target(value.strip())
        if target_id and target_id.startswith(prefixes):
            targets.append(MessageTarget(type=target_type, target_id=target_id))
    return tuple(targets)


def find_message_route(output_destinations: object, route_key: str) -> MessageRoute | None:
    return next((route for route in get_message_routes(output_destinations) if route.key == route_key), None)


def scout_send_message_enabled(team: Team) -> bool:
    """Whether scouts on this project may message through their routes. Fails closed."""
    try:
        return (
            posthoganalytics.feature_enabled(
                SCOUT_SEND_MESSAGE_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.uuid)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": team.parent_team_id or team.id, "uuid": str(team.uuid)},
                },
                send_feature_flag_events=False,
            )
            is True
        )
    except Exception:
        logger.warning("signals_scout: scout-send-message flag check failed", extra={"team_id": team.id})
        return False


def lock_scout_message_lane(*, team_id: int, skill_name: str) -> None:
    """Serialize message writes for one scout until the transaction ends. Call inside `transaction.atomic`."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"signals-scout-message:{team_id}:{skill_name}"]
        )
