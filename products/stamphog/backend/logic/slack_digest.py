"""Post a merged-PR digest to Slack via a team's Slack integration.

Renders the summary as Block Kit and posts it with a plain-text fallback for notifications. Raises
``DigestSlackError`` when the stored integration can't be resolved for the team so the caller can
record the run as failed and retry the PRs tomorrow.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from posthog.models.integration import Integration, SlackIntegration

if TYPE_CHECKING:
    from ..models import DigestChannel
    from .digest import DigestSummary

logger = structlog.get_logger(__name__)

# Slack rejects messages with more than 50 blocks; header/intro/divider/footer take a few.
_MAX_PR_BLOCKS = 40


class DigestSlackError(Exception):
    """The digest could not be posted to Slack (integration missing, mismatched, or API failure)."""


def _build_blocks(summary: DigestSummary) -> list[dict]:
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": "Merged PRs digest"}},
    ]
    if summary.intro:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": summary.intro}})
    blocks.append({"type": "divider"})
    for pr in summary.prs[:_MAX_PR_BLOCKS]:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"<{pr.url}|#{pr.pr_number} {pr.title}> — {pr.author_login}\n{pr.summary}",
                },
            }
        )
    overflow = len(summary.prs) - _MAX_PR_BLOCKS
    if overflow > 0:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"…and {overflow} more merged PRs."}})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "via stamphog"}]})
    return blocks


def _build_fallback_text(summary: DigestSummary) -> str:
    lines = [summary.intro] if summary.intro else []
    lines.extend(f"#{pr.pr_number} {pr.title} — {pr.summary}" for pr in summary.prs)
    return "\n".join(lines) or "Merged PRs digest"


def post_digest(team_id: int, digest_channel: DigestChannel, summary: DigestSummary) -> str | None:
    """Post the digest to the channel's Slack destination. Returns the message ts, or None."""
    integration = Integration.objects.filter(
        id=digest_channel.slack_integration_id, team_id=team_id, kind="slack"
    ).first()
    if integration is None:
        raise DigestSlackError(f"No slack integration {digest_channel.slack_integration_id} for team {team_id}")

    response = SlackIntegration(integration).client.chat_postMessage(
        channel=digest_channel.slack_channel_id,
        blocks=_build_blocks(summary),
        text=_build_fallback_text(summary),
    )
    ts = response.get("ts")
    return str(ts) if ts else None
