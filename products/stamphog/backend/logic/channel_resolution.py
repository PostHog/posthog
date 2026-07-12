"""Auto-provision a Slack DigestChannel when the workspace has a channel named like an audience.

Channel destination is auto-resolved, never pre-created by a human: if the team's connected Slack
workspace has a channel named exactly like an audience_key (a GitHub team slug), stamphog creates
an enabled DigestChannel row for it. Humans only ever correct or disable rows afterward — see
models.DigestChannel and logic/audiences.py for how the audience_key itself is produced.
"""

from __future__ import annotations

from typing import cast

from django.db import IntegrityError

import structlog

from posthog.models.integration import Integration, SlackIntegration

from ..facade.enums import ChannelResolutionSource
from ..models import DigestChannel

logger = structlog.get_logger(__name__)


def _fetch_channel_map(integration: Integration) -> dict[str, dict[str, str]]:
    """Public channel name -> {"id": ..., "name": ...} for one Slack integration.

    Private channels are skipped: listing them needs a real authed Slack user, and this runs from
    a background task with no request user to act as — public-only is fine for name matching.
    """
    authed_user = cast(str, (integration.config or {}).get("authed_user", {}).get("id") or "")
    channels = SlackIntegration(integration).list_channels(
        should_include_private_channels=False, authed_user=authed_user
    )
    return {channel["name"]: {"id": channel["id"], "name": channel["name"]} for channel in channels}


def resolve_slack_destination(team_id: int, audience_key: str) -> tuple[int, dict[str, str]] | None:
    """Find a Slack channel named exactly like ``audience_key`` in the team's workspace.

    Returns (slack_integration_id, {"id": ..., "name": ...}) on a match, None otherwise. Fallback
    "repo:" audience keys never match — they're skipped before the (slow) channel list is fetched.
    """
    if audience_key.startswith("repo:"):
        return None

    integration = Integration.objects.filter(team_id=team_id, kind="slack").first()
    if integration is None:
        return None

    # Fetched fresh per provisioning attempt: only never-seen audiences get here (at most a handful
    # a day), so a paginated list per attempt is fine — a Slack hiccup just retries tomorrow.
    try:
        channel_map = _fetch_channel_map(integration)
    except Exception:
        logger.warning("stamphog_channel_resolution_list_channels_failed", team_id=team_id, exc_info=True)
        return None

    channel = channel_map.get(audience_key)
    if channel is None:
        return None
    return integration.id, channel


def auto_provision_channel(team_id: int, audience_key: str) -> DigestChannel | None:
    """Create an enabled DigestChannel for (team, audience_key) if a Slack name match exists.

    No-op (returns None, logged) when: the team has no Slack integration, no channel name
    matches, or a row already exists for this (team, audience_key) — including a disabled one,
    since disabled means a human opted out and auto-provisioning must never resurrect it.
    """
    if DigestChannel.objects.for_team(team_id).filter(audience_key=audience_key).exists():
        logger.info("stamphog_channel_resolution_row_exists", team_id=team_id, audience_key=audience_key)
        return None

    destination = resolve_slack_destination(team_id, audience_key)
    if destination is None:
        logger.info("stamphog_channel_resolution_no_match", team_id=team_id, audience_key=audience_key)
        return None
    slack_integration_id, channel = destination

    try:
        row = DigestChannel.objects.for_team(team_id).create(
            team_id=team_id,
            audience_key=audience_key,
            slack_integration_id=slack_integration_id,
            slack_channel_id=channel["id"],
            slack_channel_name=channel["name"],
            enabled=True,
            resolution_source=ChannelResolutionSource.SLACK_NAME_MATCH,
        )
    except IntegrityError:
        # Lost a create race — another concurrent provisioning attempt, or a human row landed
        # in between the existence check above and this create. Nothing lost.
        logger.info("stamphog_channel_resolution_race_lost", team_id=team_id, audience_key=audience_key)
        return None

    logger.info(
        "stamphog_channel_resolution_provisioned",
        team_id=team_id,
        audience_key=audience_key,
        slack_channel_id=channel["id"],
    )
    return row
