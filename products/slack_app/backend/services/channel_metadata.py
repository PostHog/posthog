"""A Slack channel's own description: its topic, its purpose, and the user groups they tag.

This is read with plain code and no LLM, so a channel's context page can name the channel's purpose and owning
team before any summary of its messages exists.
"""

import re
import dataclasses
from datetime import UTC, datetime, timedelta

import structlog
from slack_sdk.errors import SlackApiError

from posthog.dataclasses import frozen
from posthog.models.integration import SlackIntegration

from products.slack_app.backend.models import SlackChannel

logger = structlog.get_logger(__name__)

METADATA_MAX_AGE = timedelta(days=1)
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
            group_id, handle = match.group(1), (match.group(2) or "").strip()
            if group_id not in groups or (handle and not groups[group_id].handle):
                groups[group_id] = OwnerGroup(id=group_id, handle=handle)
    return list(groups.values())


def refresh_channel_metadata(
    slack: SlackIntegration, *, slack_workspace_id: str, slack_channel_id: str, now: datetime | None = None
) -> bool:
    """Store the channel's topic, purpose and owner groups. Returns whether it stored them.

    Only public channels that are not shared with another workspace qualify, because their context page is
    readable by the whole organization.
    """
    try:
        channel = slack.client.conversations_info(channel=slack_channel_id).get("channel") or {}
    except SlackApiError as error:
        logger.warning(
            "slack_app_channel_metadata_lookup_failed",
            slack_channel_id=slack_channel_id,
            error=(error.response or {}).get("error"),
        )
        return False
    if not channel.get("is_channel") or channel.get("is_private") or channel.get("is_ext_shared"):
        return False

    topic = str((channel.get("topic") or {}).get("value") or "")
    purpose = str((channel.get("purpose") or {}).get("value") or "")
    SlackChannel.objects.update_or_create(
        slack_workspace_id=slack_workspace_id,
        slack_channel_id=slack_channel_id,
        defaults={
            "topic": topic,
            "purpose": purpose,
            "owner_groups": [dataclasses.asdict(group) for group in parse_owner_groups(topic, purpose)],
            "metadata_refreshed_at": now or datetime.now(UTC),
        },
    )
    return True
