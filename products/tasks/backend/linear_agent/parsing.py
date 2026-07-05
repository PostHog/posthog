"""Linear webhook payload parsing for the PostHog Code Linear agent.

Everything that depends on the exact shape of Linear's webhook payloads lives here so
payload drift stays contained to one module. Two payload categories are handled, both
delivered by OAuth-app-level webhooks (one URL + secret configured in Linear's developer
console, events for every workspace that installed the app):

- ``AppUserNotification`` — inbox notifications for the app's bot user: the issue was
  assigned to it, or it was @mentioned in an issue or comment.
- ``AgentSessionEvent`` — Linear's agent-session lifecycle; ``created`` fires when the
  bot is delegated an issue. Sessions must be acked with an agent activity within ~10s
  or Linear marks the agent unresponsive, so the session id is surfaced for early acking.

Reference: https://linear.app/developers/webhooks
"""

import hmac
import time
import hashlib
from dataclasses import dataclass
from typing import Any, Literal

HANDLED_WEBHOOK_TYPES = ("AppUserNotification", "AgentSessionEvent")

# Must cover Linear's retry schedule (retries span hours) or legitimate retried
# deliveries get rejected as stale. Paired with the same-length webhook dedupe TTL,
# a captured payload can never be replayed usefully: inside the window the dedupe
# key still exists, outside it the timestamp check rejects it.
WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS = 24 * 60 * 60

TriggerKind = Literal["assigned", "mentioned"]

_NOTIFICATION_KIND_BY_ACTION: dict[str, TriggerKind] = {
    "issueAssignedToYou": "assigned",
    "issueMention": "mentioned",
    "issueCommentMention": "mentioned",
}


@dataclass(frozen=True)
class LinearAgentTrigger:
    """Normalized "the bot should act on this Linear issue" event."""

    organization_id: str
    issue_id: str
    issue_identifier: str | None
    issue_title: str
    issue_description: str | None
    issue_url: str | None
    comment_body: str | None
    actor_name: str | None
    agent_session_id: str | None
    kind: TriggerKind


def verify_linear_signature(payload: bytes, signature: str | None, secret: str) -> bool:
    """Verify Linear's webhook signature: HMAC-SHA256 hex digest of the raw body,
    sent unprefixed in the ``Linear-Signature`` header."""
    if not signature:
        return False

    expected_signature = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_signature, signature)


def webhook_timestamp_valid(payload: dict[str, Any], *, now: float | None = None) -> bool:
    """Check the payload's ``webhookTimestamp`` (milliseconds) against the replay window."""
    timestamp_ms = payload.get("webhookTimestamp")
    if not isinstance(timestamp_ms, int | float) or isinstance(timestamp_ms, bool):
        return False

    current = now if now is not None else time.time()
    return abs(current - timestamp_ms / 1000) <= WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS


def _build_trigger(
    *,
    organization_id: str,
    issue: dict[str, Any],
    comment: dict[str, Any],
    actor: dict[str, Any],
    agent_session_id: str | None,
    kind: TriggerKind,
) -> LinearAgentTrigger | None:
    issue_id = issue.get("id")
    if not issue_id:
        return None

    return LinearAgentTrigger(
        organization_id=organization_id,
        issue_id=issue_id,
        issue_identifier=issue.get("identifier"),
        issue_title=issue.get("title") or "",
        issue_description=issue.get("description"),
        issue_url=issue.get("url"),
        comment_body=comment.get("body"),
        actor_name=actor.get("name"),
        agent_session_id=agent_session_id,
        kind=kind,
    )


def parse_agent_trigger(payload: dict[str, Any]) -> LinearAgentTrigger | None:
    """Extract a trigger from a verified webhook payload, or None when not actionable."""
    organization_id = payload.get("organizationId")
    if not organization_id:
        return None

    payload_type = payload.get("type")
    action = payload.get("action") or ""

    if payload_type == "AppUserNotification":
        kind = _NOTIFICATION_KIND_BY_ACTION.get(action)
        if kind is None:
            return None
        notification = payload.get("notification") or {}
        return _build_trigger(
            organization_id=organization_id,
            issue=notification.get("issue") or {},
            comment=notification.get("comment") or {},
            actor=notification.get("actor") or {},
            agent_session_id=None,
            kind=kind,
        )

    if payload_type == "AgentSessionEvent":
        # "prompted" (a follow-up message into an existing session) is not handled yet.
        if action != "created":
            return None
        session = payload.get("agentSession") or {}
        return _build_trigger(
            organization_id=organization_id,
            issue=session.get("issue") or {},
            comment=session.get("comment") or {},
            actor=session.get("creator") or {},
            agent_session_id=session.get("id"),
            kind="assigned",
        )

    return None
