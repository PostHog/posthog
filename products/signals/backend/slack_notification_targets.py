"""Slack targets for inbox notifications.

A target is the picker's `id|name` composite: a channel (`C…|#name`) or a workspace member
(`U…|@name`). Slack's `chat.postMessage` accepts either id as its `channel` and opens the direct
message for a member id, so both kinds ride in the same stored field.

A member target decides which person receives report contents, so it is resolved when it is saved:
a settings card can then say that the ping will never arrive, instead of the reviewer finding out
by never being pinged.
"""

from __future__ import annotations

import re
import logging

from rest_framework import serializers
from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration, SlackIntegration
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

from products.signals.backend.models import SignalUserAutonomyConfig
from products.signals.backend.slack_formatting import slack_channel_id_from_target

logger = logging.getLogger(__name__)

# Member ids start with U, or W for an Enterprise Grid member. Channel ids start with C, G, or D.
_MEMBER_ID_RE = re.compile(r"[UW][A-Z0-9]{4,}")

_UNRESOLVED_MEMBER_ERROR = "PostHog cannot direct message that person. Pick someone else."
_UNRESOLVED_SELF_ERROR = (
    "PostHog could not find your account in this Slack workspace. Connect your Slack account, or pick a channel."
)
_SLACK_UNAVAILABLE_ERROR = "Slack did not answer. Try saving this again in a moment."
_NO_WORKSPACE_ERROR = "Choose the Slack workspace to send these through."


def is_slack_member_target(target: str) -> bool:
    """Whether a target addresses one workspace member, which Slack delivers as a direct message."""
    return bool(_MEMBER_ID_RE.fullmatch(slack_channel_id_from_target(target)))


def saved_notification_integration(user: User) -> Integration | None:
    """The Slack workspace this user's notifications already go through, if any."""
    config = SignalUserAutonomyConfig.objects.filter(user=user).select_related("slack_notification_integration").first()
    return config.slack_notification_integration if config else None


def lookup_slack_user_id_by_email(slack: SlackIntegration, email: str) -> str | None:
    normalized_email = email.strip().lower()
    if not normalized_email:
        return None

    try:
        response = slack.client.users_lookupByEmail(email=normalized_email)
    except SlackApiError as exc:
        error_code = exc.response.get("error") if exc.response else None
        if error_code != "users_not_found":
            logger.warning(
                "signals_inbox_slack_user_email_lookup_failed",
                extra={"email": normalized_email, "error": error_code},
            )
        return None

    data = response.data if hasattr(response, "data") and isinstance(response.data, dict) else response
    if not isinstance(data, dict) or not data.get("ok"):
        return None

    slack_user = data.get("user")
    if not isinstance(slack_user, dict) or not slack_user.get("id"):
        return None
    return str(slack_user["id"])


def resolve_own_direct_message_target(user: User, integration: Integration | None) -> str:
    """Resolve a user's own Slack account in this workspace to a `U…|@name` target.

    The Slack account they linked to PostHog answers first, then their PostHog email against the
    workspace directory, which is what lets someone turn direct messages on without picking
    anything. `get_user_by_id` then decides eligibility the same way the member picker does.
    """
    if integration is None:
        raise serializers.ValidationError({"slack_notification_direct_message": _NO_WORKSPACE_ERROR})
    slack = SlackIntegration(integration)
    try:
        member_id = _linked_slack_member_id(user, integration) or (
            lookup_slack_user_id_by_email(slack, user.email) if user.email else None
        )
        member = slack.get_user_by_id(member_id) if member_id else None
    except SlackApiError:
        logger.warning("signals_slack_self_lookup_failed", extra={"integration_id": integration.id})
        raise serializers.ValidationError({"slack_notification_direct_message": _SLACK_UNAVAILABLE_ERROR})
    if member is None:
        raise serializers.ValidationError({"slack_notification_direct_message": _UNRESOLVED_SELF_ERROR})
    return f"{member['id']}|@{_member_display_name(member)}"


def validate_slack_notification_target(target: str, integration: Integration | None) -> None:
    """Resolve a member target a caller sent itself, or raise.

    A channel target needs no lookup: the picker already warns when the app is missing from the
    channel. A member target goes through the same eligibility check as the resolved one, so an
    API caller cannot store a bot, a deactivated account, a guest, or a Slack Connect member whose
    home workspace is another one.
    """
    if not is_slack_member_target(target):
        return
    if integration is None:
        raise serializers.ValidationError({"slack_notification_channel": _NO_WORKSPACE_ERROR})
    try:
        member = SlackIntegration(integration).get_user_by_id(slack_channel_id_from_target(target))
    except SlackApiError:
        logger.warning("signals_slack_member_target_lookup_failed", extra={"integration_id": integration.id})
        raise serializers.ValidationError({"slack_notification_channel": _SLACK_UNAVAILABLE_ERROR})
    if member is None:
        raise serializers.ValidationError({"slack_notification_channel": _UNRESOLVED_MEMBER_ERROR})


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


def _member_display_name(member: dict) -> str:
    profile = member.get("profile") or {}
    return profile.get("display_name") or profile.get("real_name") or member.get("name") or "you"
