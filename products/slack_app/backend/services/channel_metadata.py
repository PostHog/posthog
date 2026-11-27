"""A Slack channel's own description: its topic, its purpose, and the user groups they tag.

This is read with plain code and no LLM, so a channel's context page can name the channel's purpose and owning
team before any summary of its messages exists.
"""

import re
import html
import dataclasses

from django.core.cache import cache

import structlog

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationRecord
from posthog.models.integration import SlackIntegration
from posthog.slack.channels import is_shared_channel

from products.slack_app.backend.feature_flags import CHANNEL_CONTEXT_REQUIRED_SCOPES
from products.slack_app.backend.models import SlackChannel
from products.slack_app.backend.services.slack_conversations import lookup_channel_info
from products.slack_app.backend.services.slack_scopes import SLACK_USERGROUPS_SCOPE, has_scopes

logger = structlog.get_logger(__name__)

METADATA_REFRESH_SECONDS = 24 * 60 * 60
GROUP_LOOKUP_RETRY_SECONDS = 10 * 60
# After a rate limit or a network error, the next mention may try again once this has passed.
LOOKUP_RETRY_SECONDS = 15 * 60
# Errors that mean the app can no longer read the channel, for example because it turned private on an install
# without `groups:read`, or the bot was removed from it.
ACCESS_LOST_ERRORS = frozenset({"channel_not_found", "missing_scope", "not_in_channel"})
# Slack writes a user group tag as `<!subteam^S0123|@team-replay>`, and older clients leave out the label.
_SUBTEAM_RE = re.compile(r"<!subteam\^(S[A-Z0-9]+)(?:\|@?([^>]*))?>")


@frozen
class OwnerGroup:
    id: str
    handle: str = ""


def parse_owner_groups(*texts: str) -> list[OwnerGroup]:
    """The user groups tagged in the texts, each one once, in the order they first appear."""
    groups: dict[str, OwnerGroup] = {}
    for text in texts:
        for match in _SUBTEAM_RE.finditer(text):
            group_id, handle = match.group(1), html.unescape(match.group(2) or "").strip()
            if group_id not in groups or (handle and not groups[group_id].handle):
                groups[group_id] = OwnerGroup(id=group_id, handle=handle)
    return list(groups.values())


@frozen
class _GroupLookup:
    handles: dict[str, str]
    # False when another refresh holds the workspace read or Slack failed, so a handle may still arrive soon.
    answered: bool


def _workspace_group_handles(slack: SlackIntegration, wanted: set[str]) -> _GroupLookup:
    workspace_id = slack.integration.integration_id
    key = f"slack_app_usergroup_handles:{workspace_id}"
    cached: dict[str, str] | None = cache.get(key)
    if cached is not None and wanted <= cached.keys():
        return _GroupLookup(handles=cached, answered=True)
    # One read returns every group in the workspace and serves all its channels. At most one read per retry
    # window, so a burst of refreshes, a new group or a read that always fails cannot spend the rate limit.
    if not cache.add(f"{key}:read", 1, timeout=GROUP_LOOKUP_RETRY_SECONDS):
        return _GroupLookup(handles=cached or {}, answered=False)
    try:
        # `team_id` is required for an org-wide Enterprise Grid install. Disabled groups still name an owner.
        response = slack.client.usergroups_list(team_id=workspace_id, include_disabled=True)
    except Exception:
        logger.warning("slack_app_usergroups_lookup_failed", exc_info=True)
        return _GroupLookup(handles=cached or {}, answered=False)
    handles = {str(row.get("id")): str(row.get("handle") or "") for row in response.get("usergroups") or []}
    cache.set(key, handles, timeout=METADATA_REFRESH_SECONDS)
    return _GroupLookup(handles=handles, answered=True)


def _stored_group_handles(slack_workspace_id: str, slack_channel_id: str) -> dict[str, str]:
    stored = (
        SlackChannel.objects.filter(slack_workspace_id=slack_workspace_id, slack_channel_id=slack_channel_id)
        .values_list("owner_groups", flat=True)
        .first()
    )
    return {
        str(group["id"]): str(group["handle"])
        for group in stored or []
        if isinstance(group, dict) and group.get("id") and group.get("handle")
    }


def _refresh_slot_key(integration_id: int, slack_channel_id: str) -> str:
    return f"slack_app_channel_metadata:{integration_id}:{slack_channel_id}"


def _clear_stored_description(slack_workspace_id: str, slack_channel_id: str) -> None:
    """Forget a channel's description and keep its approval, so the organization stops reading a channel it can't."""
    SlackChannel.objects.filter(slack_workspace_id=slack_workspace_id, slack_channel_id=slack_channel_id).exclude(
        topic="", purpose="", owner_groups=[]
    ).update(topic="", purpose="", owner_groups=[])


def schedule_channel_metadata_refresh(
    integration: IntegrationRecord, slack_channel_id: str, *, is_ext_shared: bool = False
) -> None:
    """Refresh the channel's description in the background, at most once per channel per day.

    This runs on the mention path, so it never raises: a lost refresh is retried at the next mention. The scope
    check comes first because it is free, so an install that cannot read the channel never uses the day's slot.
    The feature flag is a remote call, so the task checks it. The slot is per integration, because each one has
    its own organization and flag.
    """
    # A `D…` id is a DM, which has no description, and `conversations.info` cannot read it without `im:read`.
    if slack_channel_id.startswith("D"):
        return
    slot = _refresh_slot_key(integration.id, slack_channel_id)
    acquired = False
    try:
        if not has_scopes(integration, CHANNEL_CONTEXT_REQUIRED_SCOPES):
            return
        acquired = cache.add(slot, 1, timeout=METADATA_REFRESH_SECONDS)
        if not acquired:
            return
        if is_ext_shared:
            # The event already says the channel is shared, so a description stored while it was public goes now.
            _clear_stored_description(integration.integration_id or "", slack_channel_id)
            return
        # The task module imports this one, so a module-level import here would be circular.
        from products.slack_app.backend.tasks import refresh_slack_channel_metadata  # noqa: PLC0415

        refresh_slack_channel_metadata.delay(
            team_id=integration.team_id, integration_id=integration.id, slack_channel_id=slack_channel_id
        )
    except Exception:
        logger.warning(
            "slack_app_channel_metadata_refresh_schedule_failed", integration_id=integration.id, exc_info=True
        )
        if acquired:
            # Nothing ran, so the next mention may try again.
            try:
                cache.delete(slot)
            except Exception:
                logger.warning("slack_app_channel_metadata_slot_release_failed", integration_id=integration.id)


def refresh_channel_metadata(slack: SlackIntegration, *, slack_workspace_id: str, slack_channel_id: str) -> bool:
    """Store the channel's topic, purpose and owner groups. Returns whether it stored them.

    Only public channels that are not shared beyond this workspace qualify, because their context page is
    readable by the whole organization.
    """
    lookup = lookup_channel_info(slack, slack_channel_id)
    channel = lookup.channel
    if channel is None:
        if lookup.error in ACCESS_LOST_ERRORS:
            # The day's slot stays taken: asking again tomorrow is soon enough for a channel the app can't read.
            _clear_stored_description(slack_workspace_id, slack_channel_id)
        else:
            # A rate limit or a network error: let a mention try again after a short wait, not on the next message.
            cache.set(_refresh_slot_key(slack.integration.id, slack_channel_id), 1, timeout=LOOKUP_RETRY_SECONDS)
        return False
    if not channel.get("is_channel") or channel.get("is_private") or is_shared_channel(channel):
        # A channel that was public can turn private or shared, so its old description must not stay readable.
        _clear_stored_description(slack_workspace_id, slack_channel_id)
        return False

    # Slack escapes &, < and > in this text. Tags are read before unescaping, so an escaped `&lt;` cannot form one.
    raw_topic = str((channel.get("topic") or {}).get("value") or "")
    raw_purpose = str((channel.get("purpose") or {}).get("value") or "")
    groups = parse_owner_groups(raw_topic, raw_purpose)
    known = _stored_group_handles(slack_workspace_id, slack_channel_id)
    wanted = {group.id for group in groups if not group.handle}
    lookup_answered = True
    if wanted and not slack.missing_scopes([SLACK_USERGROUPS_SCOPE]):
        group_lookup = _workspace_group_handles(slack, wanted)
        known = {**known, **group_lookup.handles}
        lookup_answered = group_lookup.answered
    groups = [group if group.handle else OwnerGroup(id=group.id, handle=known.get(group.id, "")) for group in groups]
    SlackChannel.objects.update_or_create(
        slack_workspace_id=slack_workspace_id,
        slack_channel_id=slack_channel_id,
        defaults={
            "topic": html.unescape(raw_topic),
            "purpose": html.unescape(raw_purpose),
            "owner_groups": [dataclasses.asdict(group) for group in groups],
        },
    )
    if not lookup_answered:
        cache.set(_refresh_slot_key(slack.integration.id, slack_channel_id), 1, timeout=GROUP_LOOKUP_RETRY_SECONDS)
    return True
