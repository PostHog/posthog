"""Tell the team that owns a story, in its Slack channel, that somebody just quarantined it.

The person who quarantines asks for this with a toggle, so the owning team hears about it the
moment it happens instead of in the weekly debt digest. Ownership and the channel are resolved the
same way as for the digest: the story index of the newest default-branch Storybook run names the
story's file, the repository's owners files name the team, and the team's registry entry names the
channel.

Best effort. A quarantine never fails because its notice could not be sent, and nothing retries a
notice: the weekly digest still lists the quarantine before it expires.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from urllib.parse import quote
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

import structlog
from owners_yaml.schema import TeamEntry
from slack_sdk.errors import SlackApiError

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.models.integration import Integration, SlackIntegration
from posthog.models.user import User
from posthog.ownership.github_files import fetcher_for_team
from posthog.ownership.paths import UNOWNED_TEAM, resolve_path_owners
from posthog.ph_client import ph_scoped_capture
from posthog.slack.channels import (
    MAX_BUTTON_URL_CHARS,
    MAX_SECTION_CHARS,
    SlackButton,
    SlackPostRefused,
    clip_text,
    context_block,
    fetch_channel_map,
    post_with_join,
    section_block,
)
from posthog.slack.formatting import escape_slack_mrkdwn

from ..db import WRITER_DB
from ..facade.enums import ActorType, RunType
from ..models import QuarantinedIdentifier, Repo
from . import run_queries, story_index, team_channels

logger = structlog.get_logger(__name__)

# The quarantine modal sends one request per theme variant of a story. The variants share a story
# and a team, so the team gets one notice for the lot, not one per variant.
_STORY_NOTICE_WINDOW_SECONDS = 10 * 60

_MAX_IDENTIFIER_CHARS = 160
_MAX_REASON_CHARS = 200


class NoticeOutcome(StrEnum):
    """What happened to one notice. Logged and captured, so a notice that never arrives has a reason."""

    SENT = "sent"
    ENTRY_INACTIVE = "entry_inactive"  # the quarantine was lifted or ran out before the notice went
    DUPLICATE = "duplicate"  # another theme variant of the story already notified the team
    NOT_ATTRIBUTABLE = "not_attributable"  # no story index, or the story is not in it
    OWNERSHIP_UNAVAILABLE = "ownership_unavailable"  # the owners files could not be read
    UNOWNED = "unowned"  # no owners entry covers the story's file
    NO_SLACK = "no_slack"  # the project has no Slack integration
    NO_CHANNEL = "no_channel"  # the team opted out, or its channel does not resolve
    REFUSED = "refused"  # Slack refused the post


@frozen
class NoticeMessage:
    """One post: the blocks Slack renders, and the plain text it shows wherever they do not."""

    blocks: list[dict[str, Any]]
    text: str


def _snapshot_url(repo: Repo, run_type: str, identifier: str) -> str:
    url = (
        f"{settings.SITE_URL}/project/{repo.team_id}/visual_review/repos/{repo.id}"
        f"/{quote(run_type, safe='')}/snapshots/{quote(identifier, safe='')}"
    )
    if len(url) <= MAX_BUTTON_URL_CHARS:
        return url
    # A long non-ASCII identifier can outgrow the button cap on its own, and Slack refuses the
    # whole message over one oversized button.
    return f"{settings.SITE_URL}/project/{repo.team_id}/visual_review/repos/{repo.id}/snapshots"


def _month_day(moment: datetime) -> str:
    return f"{moment:%b} {moment.day}"


def _story_key(entry: QuarantinedIdentifier) -> str:
    split = story_index.split_theme(entry.identifier)
    return f"{split.story_id}{split.browser_suffix}"


@frozen
class Owner:
    """The team that owns a story's file, or the reason there is none."""

    missing: NoticeOutcome | None
    team_slug: str = ""
    source_path: str = ""
    registry: Mapping[str, TeamEntry] = MappingProxyType({})


def _owning_team(repo: Repo, entry: QuarantinedIdentifier) -> Owner:
    if entry.run_type != RunType.STORYBOOK:
        return Owner(missing=NoticeOutcome.NOT_ATTRIBUTABLE)
    newest_run_by_type = run_queries.newest_run_by_run_type(run_queries.latest_default_branch_runs(repo.id))
    index = story_index.latest_story_index(repo, newest_run_by_type)
    if isinstance(index, str):
        return Owner(missing=NoticeOutcome.NOT_ATTRIBUTABLE)
    path = story_index.story_path(index, entry.identifier)
    if path is None:
        return Owner(missing=NoticeOutcome.NOT_ATTRIBUTABLE)
    ownership = resolve_path_owners(
        repo.repo_full_name,
        [path],
        # Somebody just acted and expects the team to hear about it soon, and nothing retries a
        # notice the budget sheds.
        files=fetcher_for_team(repo.team_id, repo.repo_full_name, priority=Priority.NORMAL),
    )
    if not ownership.resolved:
        return Owner(missing=NoticeOutcome.OWNERSHIP_UNAVAILABLE, source_path=path)
    team_slug = ownership.team_by_path.get(path, UNOWNED_TEAM)
    if team_slug == UNOWNED_TEAM:
        return Owner(missing=NoticeOutcome.UNOWNED, source_path=path)
    return Owner(missing=None, team_slug=team_slug, source_path=path, registry=ownership.registry)


def _slack_mention(slack: SlackIntegration, integration: Integration, email: str) -> str | None:
    """A mention of the PostHog user in this Slack workspace, or None when they are not a member.

    `users.lookupByEmail` also returns external Slack Connect members, whose profile emails their
    own workspace's admin controls, so a match from another workspace is not trusted.
    """
    workspace = integration.integration_id or ""
    if not email or not workspace:
        return None
    try:
        response = slack.client.users_lookupByEmail(email=email)
    except SlackApiError:
        return None
    user = response.get("user") or {}
    if not user.get("id") or user.get("team_id") != workspace:
        return None
    return f"<@{user['id']}>"


def actor_label(user: User | None, mention: str | None) -> str:
    """How the message names the person who quarantined: a Slack mention when there is one."""
    if mention:
        return mention
    if user is None:
        return "Someone"
    return f"*{escape_slack_mrkdwn(user.first_name or user.email)}*"


def build_message(
    repo: Repo,
    entry: QuarantinedIdentifier,
    *,
    actor: str,
    team_slug: str,
    source_path: str,
) -> NoticeMessage:
    split = story_index.split_theme(entry.identifier)
    story = split.story_id if split.theme else entry.identifier
    story_text = escape_slack_mrkdwn(clip_text(story, _MAX_IDENTIFIER_CHARS))
    by = f"{actor} (using an AI agent)" if entry.source == ActorType.AGENT else actor
    lead = f"{by} quarantined a story owned by you. Please check."

    expiry = (
        f"Expires {_month_day(entry.expires_at)}. Runs don't fail on this snapshot until then."
        if entry.expires_at
        else "No expiry. Runs don't fail on this snapshot until someone lifts the quarantine."
    )
    facts = (
        f"*{story_text}* {escape_slack_mrkdwn(entry.run_type)}\n"
        f'Reason: _"{escape_slack_mrkdwn(clip_text(entry.reason, _MAX_REASON_CHARS))}"_\n'
        f"{expiry}"
    )
    return NoticeMessage(
        blocks=[
            section_block(lead),
            section_block(
                clip_text(facts, MAX_SECTION_CHARS),
                SlackButton(text="Open snapshot", url=_snapshot_url(repo, entry.run_type, entry.identifier)),
            ),
            context_block(
                f"{escape_slack_mrkdwn(repo.repo_full_name)} · sent to {escape_slack_mrkdwn(team_slug)}, "
                f"which owns `{escape_slack_mrkdwn(source_path)}`"
            ),
        ],
        text=clip_text(f"{lead} {story_text}", MAX_SECTION_CHARS),
    )


def send_quarantine_notice(entry_id: UUID, team_id: int) -> NoticeOutcome:
    """Post one quarantine to the channel of the team that owns its story."""
    entry = (
        QuarantinedIdentifier.objects.using(WRITER_DB)
        .select_related("repo")
        .filter(id=entry_id, team_id=team_id)
        .first()
    )
    if entry is None or (entry.expires_at is not None and entry.expires_at <= timezone.now()):
        return _finish(entry_id, team_id, None, NoticeOutcome.ENTRY_INACTIVE)
    repo = entry.repo

    owner = _owning_team(repo, entry)
    if owner.missing is not None:
        return _finish(entry_id, team_id, entry, owner.missing, source_path=owner.source_path)
    team_slug, source_path = owner.team_slug, owner.source_path

    integration = Integration.objects.filter(team_id=repo.team_id, kind="slack").first()
    if integration is None:
        return _finish(entry_id, team_id, entry, NoticeOutcome.NO_SLACK, team_slug=team_slug)
    channels_by_name = fetch_channel_map(integration, source="visual_review")
    delivery = team_channels.resolve_team_channel(
        team_slug, owner.registry, channels_by_name, feature="quarantine_notice"
    )
    if delivery is None:
        return _finish(entry_id, team_id, entry, NoticeOutcome.NO_CHANNEL, team_slug=team_slug)

    # Taken as late as possible, so a variant whose notice stopped earlier does not silence the next.
    story_lock = f"visual_review_quarantine_notice:{repo.id}:{entry.run_type}:{_story_key(entry)}"
    if not cache.add(story_lock, True, timeout=_STORY_NOTICE_WINDOW_SECONDS):
        return _finish(entry_id, team_id, entry, NoticeOutcome.DUPLICATE, team_slug=team_slug)

    slack = SlackIntegration(integration, source="visual_review")
    user = (
        User.objects.filter(id=entry.created_by_id).only("id", "first_name", "email", "distinct_id").first()
        if entry.created_by_id
        else None
    )
    mention = _slack_mention(slack, integration, user.email) if user is not None else None
    message = build_message(repo, entry, actor=actor_label(user, mention), team_slug=team_slug, source_path=source_path)
    try:
        post_with_join(slack, delivery.channel_id, message.blocks, message.text, channel_name=delivery.channel_name)
    except SlackPostRefused as e:
        logger.warning("visual_review.quarantine_notice_refused", team_slug=team_slug, error=str(e))
        return _finish(entry_id, team_id, entry, NoticeOutcome.REFUSED, team_slug=team_slug, user=user)
    return _finish(entry_id, team_id, entry, NoticeOutcome.SENT, team_slug=team_slug, user=user)


def _finish(
    entry_id: UUID,
    team_id: int,
    entry: QuarantinedIdentifier | None,
    outcome: NoticeOutcome,
    *,
    team_slug: str = "",
    source_path: str = "",
    user: User | None = None,
) -> NoticeOutcome:
    """Log the outcome and capture it, so the toggle's use can be followed from request to post."""
    logger.info(
        "visual_review.quarantine_notice",
        entry_id=str(entry_id),
        team_id=team_id,
        outcome=str(outcome),
        team_slug=team_slug,
        source_path=source_path,
    )
    if entry is None:
        return outcome
    try:
        with ph_scoped_capture() as capture_ph_event:
            capture_ph_event(
                distinct_id=user.distinct_id if user is not None and user.distinct_id else str(entry.repo_id),
                event="vr_quarantine_owner_notice",
                properties={
                    "outcome": str(outcome),
                    "run_type": entry.run_type,
                    "owner_team": team_slug or None,
                    "team_id": team_id,
                },
            )
    except Exception:
        logger.warning("visual_review.quarantine_notice_capture_failed", entry_id=str(entry_id), exc_info=True)
    return outcome
