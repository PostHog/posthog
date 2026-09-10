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
import hashlib
import logging

from django.core.cache import cache

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
_SLACK_MISSING_SCOPE_ERROR = (
    "Your Slack connection cannot list workspace members. Reconnect Slack, and then save this setting again."
)
_NO_WORKSPACE_ERROR = "Choose the Slack workspace to send these through."
_MEMBER_LOOKUPS_PER_MINUTE = 30


def is_slack_member_target(target: str) -> bool:
    """Whether a target addresses one workspace member, which Slack delivers as a direct message."""
    return bool(_MEMBER_ID_RE.fullmatch(slack_channel_id_from_target(target)))


def saved_notification_integration(user: User) -> Integration | None:
    """The Slack workspace this user's notifications already go through, if any."""
    config = SignalUserAutonomyConfig.objects.filter(user=user).select_related("slack_notification_integration").first()
    return config.slack_notification_integration if config else None


def lookup_slack_user_id_by_email(
    slack: SlackIntegration, email: str, integration: Integration | None = None
) -> str | None:
    integration = integration or slack.integration
    normalized_email = email.strip().lower()
    if not normalized_email:
        return None

    email_hash = hashlib.sha256(normalized_email.encode()).hexdigest()
    lookup_key = f"signals/slack/{integration.id}/users_by_email/{email_hash}"
    cached_member_id = cache.get(lookup_key)
    if cached_member_id is not None:
        return cached_member_id or None

    _take_member_lookup_budget(integration)
    try:
        response = slack.client.users_lookupByEmail(email=normalized_email)
    except SlackApiError as exc:
        error_code = exc.response.get("error") if exc.response else None
        if error_code == "users_not_found":
            cache.set(lookup_key, "", 60 * 60)
            return None
        logger.warning(
            "signals_inbox_slack_user_email_lookup_failed",
            extra={"integration_id": integration.id, "error": error_code},
        )
        raise

    data = response.data if hasattr(response, "data") and isinstance(response.data, dict) else response
    slack_user = data.get("user") if isinstance(data, dict) and data.get("ok") else None
    member_id = str(slack_user["id"]) if isinstance(slack_user, dict) and slack_user.get("id") else None
    cache.set(lookup_key, member_id or "", 60 * 60)
    return member_id


def _take_member_lookup_budget(integration: Integration) -> None:
    budget_key = f"signals/slack/{integration.id}/member_lookup_budget"
    try:
        lookups = 1 if cache.add(budget_key, 1, 60) else cache.incr(budget_key)
    except ValueError:
        lookups = 1
    if lookups > _MEMBER_LOOKUPS_PER_MINUTE:
        raise serializers.ValidationError({"slack_notification_direct_message": _SLACK_UNAVAILABLE_ERROR})


def _cached_slack_member(slack: SlackIntegration, integration: Integration, member_id: str) -> dict | None:
    lookup_key = f"slack/{integration.id}/users/{member_id}"
    cached_lookup = cache.get(lookup_key)
    if cached_lookup is not None:
        return cached_lookup[0] if cached_lookup else None

    _take_member_lookup_budget(integration)
    member = slack.get_user_by_id(member_id)
    serialized_lookup = (
        [{"id": member["id"], "name": member.get("name", ""), "display_name": _member_display_name(member)}]
        if member
        else []
    )
    cache.set(lookup_key, serialized_lookup, 60 * 60)
    return serialized_lookup[0] if serialized_lookup else None


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
            lookup_slack_user_id_by_email(slack, user.email, integration) if user.email else None
        )
        member = _cached_slack_member(slack, integration, member_id) if member_id else None
    except SlackApiError as exc:
        logger.warning("signals_slack_self_lookup_failed", extra={"integration_id": integration.id})
        error_code = exc.response.get("error") if exc.response else None
        message = _SLACK_MISSING_SCOPE_ERROR if error_code == "missing_scope" else _SLACK_UNAVAILABLE_ERROR
        raise serializers.ValidationError({"slack_notification_direct_message": message})
    if member is None:
        raise serializers.ValidationError({"slack_notification_direct_message": _UNRESOLVED_SELF_ERROR})
    return f"{member['id']}|@{_member_display_name(member)}"


def validate_slack_notification_target(user: User, target: str, integration: Integration | None) -> None:
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
    resolved_target = resolve_own_direct_message_target(user, integration)
    if slack_channel_id_from_target(resolved_target) != slack_channel_id_from_target(target):
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
    return (
        profile.get("display_name")
        or profile.get("real_name")
        or member.get("display_name")
        or member.get("name")
        or "you"
    )
