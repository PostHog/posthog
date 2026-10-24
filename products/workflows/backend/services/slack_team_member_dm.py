"""Slack direct message to a PostHog team member, sent by the "Message team member on Slack" workflow step.

The recipient comes from a workflow variable, so Hog code chooses who receives the message. The send only
goes to an active member of the project's organization who can access the project. A value that a customer
controls therefore cannot point the PostHog bot at an arbitrary person in the Slack workspace.
"""

import uuid
import hashlib
from urllib.parse import urlparse

from django.db import models

import redis
import structlog
from slack_sdk.errors import SlackApiError

from posthog.dataclasses import frozen
from posthog.egress.slack.client import SlackWebClient
from posthog.models.integration import Integration, SlackIntegration
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration
from posthog.redis import get_client
from posthog.slack.formatting import escape_slack_mrkdwn
from posthog.user_permissions import user_can_access_team

logger = structlog.get_logger(__name__)

# A reservation only has to outlive one request. A worker killed mid-send frees the step this many
# seconds later.
_IN_FLIGHT_TTL_SECONDS = 30
# A step can be dispatched again long after its first attempt, for example when a worker dies before
# it records the result, so a sent message stays replayable for a day.
_SENT_TTL_SECONDS = 24 * 60 * 60
_IN_FLIGHT_PREFIX = "inflight:"
_SENT_PREFIX = "sent:"


class TeamMemberSlackDmOutcome(models.TextChoices):
    SENT = "sent", "Sent"
    SKIPPED = "skipped", "Skipped"


@frozen
class TeamMemberSlackDm:
    recipient: str
    text: str
    button_url: str = ""
    button_text: str = ""


@frozen
class TeamMemberSlackDmResult:
    outcome: TeamMemberSlackDmOutcome
    detail: str
    slack_user_id: str | None = None


class TeamMemberSlackDmUndeliverable(Exception):
    """The message cannot reach the recipient. The text goes verbatim to the workflow logs."""


class TeamMemberSlackDmInFlight(Exception):
    """Another attempt of the same workflow step is still sending this message."""


class _SendOutcomeUnknown(Exception):
    def __init__(self, slack_user_id: str) -> None:
        super().__init__(slack_user_id)
        self.slack_user_id = slack_user_id


def send_team_member_slack_dm(
    *, team: Team, integration: Integration, message: TeamMemberSlackDm, idempotency_key: str
) -> TeamMemberSlackDmResult:
    # The worker retries a request whose response it never received. A Slack message cannot be
    # taken back, so the retry must not send a second one.
    client = get_client()
    key = f"workflows:slack_dm_team_member:v1:{hashlib.sha256(f'{team.id}:{idempotency_key}'.encode()).hexdigest()}"
    token = f"{_IN_FLIGHT_PREFIX}{uuid.uuid4()}"
    if not client.set(key, token, nx=True, ex=_IN_FLIGHT_TTL_SECONDS):
        held = _decode(client.get(key))
        if held.startswith(_SENT_PREFIX):
            return TeamMemberSlackDmResult(
                outcome=TeamMemberSlackDmOutcome.SENT,
                detail="The message was already sent.",
                slack_user_id=held.removeprefix(_SENT_PREFIX),
            )
        raise TeamMemberSlackDmInFlight()

    try:
        slack_user_id = _deliver(team=team, integration=integration, message=message)
    except _SendOutcomeUnknown as exc:
        client.set(key, f"{_SENT_PREFIX}{exc.slack_user_id}", ex=_SENT_TTL_SECONDS)
        raise TeamMemberSlackDmUndeliverable(
            "Slack did not confirm the message, so the team member may or may not have it. "
            "Check Slack before you run this step again."
        ) from exc
    except Exception:
        _release(client, key, token)
        raise

    if slack_user_id is None:
        _release(client, key, token)
        return TeamMemberSlackDmResult(
            outcome=TeamMemberSlackDmOutcome.SKIPPED, detail="The recipient is empty, so no Slack message was sent."
        )
    client.set(key, f"{_SENT_PREFIX}{slack_user_id}", ex=_SENT_TTL_SECONDS)
    return TeamMemberSlackDmResult(
        outcome=TeamMemberSlackDmOutcome.SENT, detail="The message was sent.", slack_user_id=slack_user_id
    )


def _deliver(*, team: Team, integration: Integration, message: TeamMemberSlackDm) -> str | None:
    """Send the message and return the Slack member id it went to, or None when the recipient is empty."""
    recipient = message.recipient.strip()
    if not recipient:
        return None
    user = _resolve_team_member(team, recipient)

    slack = SlackIntegration(integration, source="workflows_slack_dm_team_member")
    client = slack.client
    slack_user_id = _resolve_slack_member(slack, client, integration, user)
    if slack_user_id is None:
        raise TeamMemberSlackDmUndeliverable(
            f"PostHog could not find {_display_name(user)} in this Slack workspace. Ask them to connect "
            "their Slack account to PostHog, or to use the same email address in Slack and PostHog."
        )

    # The text is rendered from workflow variables, which can carry customer-controlled values.
    # Escaping stops those from becoming disguised links or mentions in a message from the PostHog bot.
    text = escape_slack_mrkdwn(message.text)
    try:
        client.chat_postMessage(
            channel=slack_user_id,
            text=text,
            blocks=_message_blocks(text=text, button_url=message.button_url, button_text=message.button_text),
            unfurl_links=False,
        )
    except SlackApiError as exc:
        logger.warning("slack_dm_team_member_failed", team_id=team.id, error=_slack_error_code(exc))
        raise TeamMemberSlackDmUndeliverable(
            f"Slack refused the message ({_slack_error_code(exc) or 'unknown error'})."
        ) from exc
    except Exception as exc:
        logger.warning("slack_dm_team_member_outcome_unknown", team_id=team.id, exc_info=True)
        raise _SendOutcomeUnknown(slack_user_id) from exc
    return slack_user_id


def _resolve_team_member(team: Team, recipient: str) -> User:
    """The active organization member that an email address or PostHog user id names."""
    memberships = OrganizationMembership.objects.filter(
        organization_id=team.organization_id, user__is_active=True
    ).select_related("user")
    if "@" in recipient:
        # Profile emails often differ in case from the stored PostHog email.
        membership = memberships.filter(user__email__iexact=recipient).first()
    elif recipient.isdigit():
        membership = memberships.filter(user_id=int(recipient)).first()
    else:
        try:
            membership = memberships.filter(user__uuid=uuid.UUID(recipient)).first()
        except ValueError:
            raise TeamMemberSlackDmUndeliverable(
                f"The recipient '{recipient}' is not an email address or a PostHog user ID."
            )
    if membership is None or not user_can_access_team(membership.user, team):
        raise TeamMemberSlackDmUndeliverable(
            f"The recipient '{recipient}' is not a member of this project, so PostHog did not message them."
        )
    return membership.user


def _resolve_slack_member(
    slack: SlackIntegration, client: SlackWebClient, integration: Integration, user: User
) -> str | None:
    """The user's Slack member id in this workspace, or None when they cannot receive a DM.

    The Slack account the user linked to PostHog answers first. Their PostHog email against the
    workspace directory is the fallback, so the step works before anyone links an account.
    `get_user_by_id` then rejects bots, guests, deactivated members, and Slack Connect members whose
    home workspace is another one. `users.lookupByEmail` also returns Slack Connect members, whose
    profile email is set by another workspace's admin.
    """
    try:
        member_id = _linked_slack_member_id(user, integration) or _slack_member_id_by_email(client, user.email)
        if not member_id:
            return None
        return member_id if slack.get_user_by_id(member_id) else None
    except SlackApiError as exc:
        if _slack_error_code(exc) == "missing_scope":
            raise TeamMemberSlackDmUndeliverable(
                "PostHog cannot look up members in this Slack workspace. Reconnect Slack to give it the "
                "users:read and users:read.email permissions."
            ) from exc
        raise TeamMemberSlackDmUndeliverable(
            f"Slack did not answer the member lookup ({_slack_error_code(exc) or 'unknown error'})."
        ) from exc


def _linked_slack_member_id(user: User, integration: Integration) -> str | None:
    link = (
        UserIntegration.objects.filter(
            user=user,
            kind=UserIntegration.IntegrationKind.SLACK,
            config__slack_team_id=integration.integration_id,
        )
        .order_by("-created_at")
        .first()
    )
    return link.integration_id if link else None


def _slack_member_id_by_email(client: SlackWebClient, email: str) -> str | None:
    if not email:
        return None
    try:
        response = client.users_lookupByEmail(email=email)
    except SlackApiError as exc:
        if _slack_error_code(exc) == "users_not_found":
            return None
        raise
    user = response.get("user") or {}
    return str(user["id"]) if user.get("id") else None


def _release(client: redis.Redis, key: str, token: str) -> None:
    """Free the reservation so an immediate retry can send, unless another attempt took it over."""
    if _decode(client.get(key)) == token:
        client.delete(key)


def _decode(value: object) -> str:
    if value is None:
        return ""
    return value.decode() if isinstance(value, bytes) else str(value)


def _slack_error_code(exc: SlackApiError) -> str | None:
    return exc.response.get("error") if exc.response else None


def _display_name(user: User) -> str:
    return f"{user.first_name} {user.last_name}".strip() or user.email


def is_valid_button_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _message_blocks(*, text: str, button_url: str, button_text: str) -> list[dict]:
    blocks: list[dict] = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
    if button_url:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": button_text or "Open"},
                        "url": button_url,
                    }
                ],
            }
        )
    return blocks
