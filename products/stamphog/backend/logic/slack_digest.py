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


def _escape_mrkdwn(text: str) -> str:
    """Neutralize Slack mrkdwn control characters in attacker-controlled text.

    PR titles, author logins, and model-generated summaries come from outside contributors. Escaping
    ``&``/``<``/``>`` stops a merged PR from smuggling ``<!channel>`` mentions or breaking out of a link
    into the digest channel; Slack renders the escaped entities back as the literal characters.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _link(url: str, label: str) -> str:
    # url is trusted (built from the GitHub PR URL); the label is untrusted, so escape it and drop the
    # `|` that would otherwise split the link syntax.
    return f"<{url}|{_escape_mrkdwn(label).replace('|', '/')}>"


def _build_blocks(summary: DigestSummary) -> list[dict]:
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": "Merged PRs digest"}},
    ]
    if summary.intro:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": _escape_mrkdwn(summary.intro)}})
    blocks.append({"type": "divider"})
    for pr in summary.prs[:_MAX_PR_BLOCKS]:
        link = _link(pr.url, f"#{pr.pr_number} {pr.title}")
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{link} — {_escape_mrkdwn(pr.author_login)}\n{_escape_mrkdwn(pr.summary)}",
                },
            }
        )
    overflow = len(summary.prs) - _MAX_PR_BLOCKS
    if overflow > 0:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"…and {overflow} more merged PRs."}})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "via stamphog"}]})
    return blocks


def _build_fallback_text(summary: DigestSummary) -> str:
    # The top-level `text` fallback is parsed for mentions too, so escape it the same way.
    lines = [_escape_mrkdwn(summary.intro)] if summary.intro else []
    lines.extend(f"#{pr.pr_number} {_escape_mrkdwn(pr.title)} — {_escape_mrkdwn(pr.summary)}" for pr in summary.prs)
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
