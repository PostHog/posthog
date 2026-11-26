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
from products.slack_app.backend.services.slack_conversations import fetch_channel_info
from products.slack_app.backend.services.slack_scopes import has_scopes

logger = structlog.get_logger(__name__)

METADATA_REFRESH_SECONDS = 24 * 60 * 60
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


def _refresh_slot_key(integration_id: int, slack_channel_id: str) -> str:
    return f"slack_app_channel_metadata:{integration_id}:{slack_channel_id}"


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
    if is_ext_shared or slack_channel_id.startswith("D"):
        return
    try:
        if not has_scopes(integration, CHANNEL_CONTEXT_REQUIRED_SCOPES):
            return
        if not cache.add(_refresh_slot_key(integration.id, slack_channel_id), 1, timeout=METADATA_REFRESH_SECONDS):
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


def refresh_channel_metadata(slack: SlackIntegration, *, slack_workspace_id: str, slack_channel_id: str) -> bool:
    """Store the channel's topic, purpose and owner groups. Returns whether it stored them.

    Only public channels that are not shared beyond this workspace qualify, because their context page is
    readable by the whole organization.
    """
    channel = fetch_channel_info(slack, slack_channel_id)
    if channel is None:
        # Slack could not say, so free the day's slot and let the next mention try again.
        cache.delete(_refresh_slot_key(slack.integration.id, slack_channel_id))
        return False
    stored = SlackChannel.objects.filter(slack_workspace_id=slack_workspace_id, slack_channel_id=slack_channel_id)
    if not channel.get("is_channel") or channel.get("is_private") or is_shared_channel(channel):
        # A channel that was public can turn private or shared, so its old description must not stay readable.
        stored.update(topic="", purpose="", owner_groups=[])
        return False

    # Slack escapes &, < and > in this text. Tags are read before unescaping, so an escaped `&lt;` cannot form one.
    raw_topic = str((channel.get("topic") or {}).get("value") or "")
    raw_purpose = str((channel.get("purpose") or {}).get("value") or "")
    SlackChannel.objects.update_or_create(
        slack_workspace_id=slack_workspace_id,
        slack_channel_id=slack_channel_id,
        defaults={
            "topic": html.unescape(raw_topic),
            "purpose": html.unescape(raw_purpose),
            "owner_groups": [dataclasses.asdict(group) for group in parse_owner_groups(raw_topic, raw_purpose)],
        },
    )
    return True
