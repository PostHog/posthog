"""Find-or-create the ``#posthog-inbox`` channel and persist it as the team's signal notification channel."""

from __future__ import annotations

from django.core.cache import cache

import structlog
from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration, SlackIntegration

logger = structlog.get_logger(__name__)

INBOX_CHANNEL_NAME = "posthog-inbox"
# Creating a public channel and inviting members both require this scope.
INBOX_CHANNEL_REQUIRED_SCOPES: frozenset[str] = frozenset({"channels:manage"})
# Onboarding also DMs the installer and posts reports, both needing chat:write. Gated on scopes, not a flag.
INBOX_ONBOARDING_REQUIRED_SCOPES: frozenset[str] = INBOX_CHANNEL_REQUIRED_SCOPES | frozenset({"chat:write"})

# Just long enough to absorb a concurrent install/join racing to create the same channel.
_CHANNEL_CLAIM_TTL_SECONDS = 60

# Cap the channel scan so a huge workspace (or a non-advancing cursor) can't loop unbounded.
# 50 * 200 = 10k channels; past that we bail to create / manual instructions.
_MAX_CHANNEL_LIST_PAGES = 50


def has_inbox_scopes(integration: Integration) -> bool:
    """Whether the install granted the onboarding scopes. Gated on this rather than a feature flag."""
    return not SlackIntegration(integration).missing_scopes(INBOX_ONBOARDING_REQUIRED_SCOPES)


def _get_team_channel(team_id: int) -> str | None:
    from products.signals.backend.facade.api import (
        get_default_slack_notification_channel,  # noqa: PLC0415 — keeps the signals temporal stack off the slack import path
    )

    return get_default_slack_notification_channel(team_id)


def _set_team_channel(team_id: int, value: str) -> None:
    from products.signals.backend.facade.api import (
        set_default_slack_notification_channel,  # noqa: PLC0415 — keeps the signals temporal stack off the slack import path
    )

    set_default_slack_notification_channel(team_id, value)


def _channel_target(channel_id: str, channel_name: str) -> str:
    """Serialize to the "<id>|#name" form the signals notifier expects."""
    name = channel_name if channel_name.startswith("#") else f"#{channel_name}"
    return f"{channel_id}|{name}"


def channel_id_from_target(value: str) -> str:
    return value.split("|", 1)[0].strip()


def channel_name_from_target(value: str) -> str:
    pipe = value.find("|")
    return value[pipe + 1 :].strip() if pipe != -1 else f"#{INBOX_CHANNEL_NAME}"


def _channel_exists(slack: SlackIntegration, channel_id: str) -> bool:
    try:
        channel = slack.client.conversations_info(channel=channel_id).get("channel") or {}
    except SlackApiError as e:
        # Fail safe: only a definitive "gone" answer replaces a configured channel; a transient error
        # (ratelimited, network) must not clobber the team's existing default notification channel.
        return e.response.get("error") not in ("channel_not_found", "channel_is_archived")
    return bool(channel.get("id")) and not channel.get("is_archived", False)


def _find_inbox_channel(slack: SlackIntegration) -> tuple[str, str] | None:
    """Return (channel_id, "#name") for an existing #posthog-inbox public channel, else None.

    Bounded by ``_MAX_CHANNEL_LIST_PAGES`` and fails closed (None) on any Slack error.
    """
    cursor: str | None = None
    for _ in range(_MAX_CHANNEL_LIST_PAGES):
        try:
            response = slack.client.conversations_list(
                exclude_archived=True, types="public_channel", limit=200, cursor=cursor or None
            )
        except SlackApiError as e:
            logger.warning("slack_app_inbox_channel_list_failed", error=e.response.get("error"))
            return None
        channels: list[dict] = response.get("channels", [])
        for channel in channels:
            if channel.get("name") == INBOX_CHANNEL_NAME:
                return channel["id"], f"#{INBOX_CHANNEL_NAME}"
        cursor = (response.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            return None
    logger.warning("slack_app_inbox_channel_scan_exhausted")
    return None


def _claim_channel_creation(slack_team_id: str) -> bool:
    return bool(
        cache.add(f"slack_app:inbox_channel_create:v1:{slack_team_id}", True, timeout=_CHANNEL_CLAIM_TTL_SECONDS)
    )


def ensure_inbox_channel(integration: Integration) -> tuple[str, str] | None:
    """Find-or-create #posthog-inbox, persist it as the team's default notification channel,
    and return (channel_id, "#name"). Returns None when the channel must be created but the
    install lacks ``channels:manage`` — callers fall back to manual instructions.

    Idempotent: reuses the configured channel, then any existing #posthog-inbox, before creating.
    """
    slack = SlackIntegration(integration)
    team_id = integration.team_id

    configured = _get_team_channel(team_id)
    if configured:
        channel_id = channel_id_from_target(configured)
        if _channel_exists(slack, channel_id):
            return channel_id, channel_name_from_target(configured)

    # Without channels:manage we can't create, so the only option is to find an already-created channel.
    if slack.missing_scopes(INBOX_CHANNEL_REQUIRED_SCOPES):
        existing = _find_inbox_channel(slack)
        if existing:
            _set_team_channel(team_id, _channel_target(*existing))
            return existing
        return None

    if not _claim_channel_creation(integration.integration_id):
        # Another actor holds the create claim. Reuse what they made; if not visible yet, bail rather
        # than racing a second create — the claim holder will finish and persist it.
        existing = _find_inbox_channel(slack)
        if existing:
            _set_team_channel(team_id, _channel_target(*existing))
            return existing
        return None

    # Create straight away instead of scanning every channel first — a full conversations_list sweep is
    # heavy and rate-limit-hungry, and on a fresh install (the common case) it finds nothing. If the
    # channel already exists Slack answers name_taken; only then do we pay for a scan to resolve its id.
    try:
        channel: dict = slack.client.conversations_create(name=INBOX_CHANNEL_NAME, is_private=False)["channel"]
        result: tuple[str, str] = (channel["id"], f"#{INBOX_CHANNEL_NAME}")
    except SlackApiError as e:
        if e.response.get("error") != "name_taken":
            logger.warning("slack_app_inbox_create_failed", integration_id=integration.id, error=str(e))
            return None
        found = _find_inbox_channel(slack)
        if found is None:
            logger.warning("slack_app_inbox_name_taken_but_not_found", integration_id=integration.id)
            return None
        result = found

    _set_team_channel(team_id, _channel_target(*result))
    return result


def invite_user_to_inbox(integration: Integration, channel_id: str, slack_user_id: str) -> bool:
    """Invite a Slack user into the inbox channel; existing membership counts as success.

    A bot isn't auto-added to a channel it creates and can't invite others to one it's not in, so on
    ``not_in_channel`` the bot joins and retries.
    """
    slack = SlackIntegration(integration)
    for attempt in range(2):
        try:
            slack.client.conversations_invite(channel=channel_id, users=slack_user_id)
            return True
        except SlackApiError as e:
            error = e.response.get("error")
            if error == "already_in_channel":
                return True
            if error == "not_in_channel" and attempt == 0:
                try:
                    slack.client.conversations_join(channel=channel_id)
                except SlackApiError as join_error:
                    logger.warning(
                        "slack_app_inbox_join_failed",
                        integration_id=integration.id,
                        error=join_error.response.get("error"),
                    )
                    return False
                continue
            logger.warning("slack_app_inbox_invite_failed", integration_id=integration.id, error=error)
            return False
    return False


def is_inbox_channel(integration: Integration, channel_id: str) -> bool:
    """True when ``channel_id`` is this team's inbox channel — by configured id, else by name
    (the name fallback covers the window before the team default is written)."""
    configured = _get_team_channel(integration.team_id)
    if configured and channel_id_from_target(configured) == channel_id:
        return True
    try:
        channel = SlackIntegration(integration).client.conversations_info(channel=channel_id).get("channel") or {}
    except SlackApiError:
        return False
    return channel.get("name") == INBOX_CHANNEL_NAME


def _is_channel_member(slack: SlackIntegration, channel_id: str, slack_user_id: str) -> bool:
    """Whether ``slack_user_id`` is already in ``channel_id``. Bounded + fails closed (False)."""
    cursor: str | None = None
    for _ in range(_MAX_CHANNEL_LIST_PAGES):
        try:
            response = slack.client.conversations_members(channel=channel_id, limit=200, cursor=cursor or None)
        except SlackApiError:
            return False
        if slack_user_id in (response.get("members") or []):
            return True
        cursor = (response.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            return False
    return False
