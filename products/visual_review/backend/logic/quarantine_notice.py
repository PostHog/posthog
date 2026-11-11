"""Tell the team that owns a story, in its Slack channel, that somebody just quarantined it.

The person who quarantines asks for this, so the owning team hears about it at once instead of in
the weekly debt digest. It reuses the digest's pieces: the same owner lookup, the same channel, and
the same rendering of a quarantine. A story no team owns gets no notice, because the message says
"owned by you" and the maintainers already see unowned items in the digest.

Best effort. A quarantine never fails because its notice could not be sent, and nothing retries a
notice.
"""

from __future__ import annotations

from uuid import UUID

from django.utils import timezone

import structlog

from posthog.ownership.paths import UNOWNED_TEAM
from posthog.slack.channels import clip_text, section_block
from posthog.slack.formatting import escape_slack_mrkdwn

from ..db import WRITER_DB
from ..facade.enums import ActorType
from ..models import QuarantinedIdentifier, Repo
from . import owners, run_queries, story_index, team_channels
from .debt_digest import display_names, quarantine_facts, snapshot_button
from .run_queries import SnapshotKey
from .team_channels import SlackMessage

logger = structlog.get_logger(__name__)

_MAX_IDENTIFIER_CHARS = 160


def build_message(repo: Repo, entry: QuarantinedIdentifier, actor: str, source_path: str) -> SlackMessage:
    by = f"{actor} (using an AI agent)" if entry.source == ActorType.AGENT else actor
    lead = f"*{escape_slack_mrkdwn(by)}* quarantined a story owned by you. Please check."
    # The story without its theme: one notice covers every theme variant quarantined with it.
    story = escape_slack_mrkdwn(clip_text(story_index.split_theme(entry.identifier).rest, _MAX_IDENTIFIER_CHARS))
    facts = quarantine_facts(entry, {entry.created_by_id or 0: actor}, timezone.now())
    return SlackMessage(
        blocks=[
            section_block(lead),
            section_block(
                f"*{story}* {escape_slack_mrkdwn(entry.run_type)}\n{facts}",
                snapshot_button(repo, entry.run_type, entry.identifier, "Open snapshot"),
            ),
            # The path comes from the repository, so it renders as plain text: in mrkdwn a backtick in it
            # would close the code span and let Slack auto-link whatever follows.
            {
                "type": "context",
                "elements": [
                    {
                        "type": "plain_text",
                        "text": clip_text(f"{repo.repo_full_name} · {source_path}", 2000),
                        "emoji": False,
                    }
                ],
            },
        ],
        text=f"{lead} {story}",
    )


def send_quarantine_notice(entry_id: UUID, team_id: int) -> bool:
    """Post one quarantine to the channel of the team that owns its story. False when nothing was posted."""
    entry = (
        QuarantinedIdentifier.objects.using(WRITER_DB)
        .select_related("repo")
        .filter(id=entry_id, team_id=team_id)
        .first()
    )
    if entry is None or (entry.expires_at is not None and entry.expires_at <= timezone.now()):
        logger.info("visual_review.quarantine_notice_inactive", entry_id=str(entry_id), team_id=team_id)
        return False
    repo = entry.repo

    key = SnapshotKey(run_type=entry.run_type, identifier=entry.identifier)
    found = owners.snapshot_owners(
        repo, [key], run_queries.newest_run_by_run_type(run_queries.latest_default_branch_runs(repo.id))
    )
    team_slug = found.team_by_key.get(key)
    if team_slug is None or team_slug == UNOWNED_TEAM:
        logger.info("visual_review.quarantine_notice_no_owner", entry_id=str(entry_id), team_id=team_id)
        return False

    workspace = team_channels.open_workspace(repo.team_id)
    if workspace is None:
        return False
    author_id = entry.created_by_id or 0
    actor = display_names({author_id} if author_id else set()).get(author_id, "Someone")
    message = build_message(repo, entry, actor, found.path_by_key[key])
    posted = team_channels.post_to_team(workspace, team_slug, found.registry, message)
    logger.info("visual_review.quarantine_notice", entry_id=str(entry_id), team_slug=team_slug, posted=posted)
    return posted
