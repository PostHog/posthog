"""Post a merged-PR digest to Slack via a team's Slack integration.

Renders the summary as Block Kit and posts it with a plain-text fallback for notifications. Raises
``DigestSlackError`` when the stored integration can't be resolved for the team so the caller can
record the run as failed and retry the PRs tomorrow.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from slack_sdk.errors import SlackApiError
from slack_sdk.web import SlackResponse

from posthog.models.integration import Integration, SlackIntegration

if TYPE_CHECKING:
    from ..models import DigestChannel
    from .digest import DigestPRSummary, DigestSummary

logger = structlog.get_logger(__name__)

# Slack rejects messages with more than 50 blocks; header/intro/divider/footer take a few.
_MAX_PR_BLOCKS = 40
# Slack rejects a section whose mrkdwn text exceeds 3000 chars, and the failure path unlinks the
# claimed PRs — an oversized LLM summary would make every daily retry fail the same way forever.
_MAX_SECTION_CHARS = 2900


def _clip(text: str, limit: int = _MAX_SECTION_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


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


def _pr_label(pr: DigestPRSummary, *, qualify: bool) -> str:
    """``#412 Title``, or ``owner/repo#412 Title`` once the digest carries more than one repo.

    A team audience collects merges from every repo it owns code in, and PR numbers only mean
    something within a repo. Qualifying unconditionally would put the same constant prefix on
    every line of the far more common single-repo digest.
    """
    number = f"{pr.repository}#{pr.pr_number}" if qualify and pr.repository else f"#{pr.pr_number}"
    return f"{number} {pr.title}"


def _spans_repositories(summary: DigestSummary) -> bool:
    return len({pr.repository for pr in summary.prs}) > 1


def _build_blocks(summary: DigestSummary) -> list[dict]:
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": "Merged PRs digest"}},
    ]
    if summary.intro:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": _clip(_escape_mrkdwn(summary.intro))}})
    blocks.append({"type": "divider"})
    qualify = _spans_repositories(summary)
    for pr in summary.prs[:_MAX_PR_BLOCKS]:
        link = _link(pr.url, _pr_label(pr, qualify=qualify))
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": _clip(f"{link} — {_escape_mrkdwn(pr.author_login)}\n{_escape_mrkdwn(pr.summary)}"),
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
    qualify = _spans_repositories(summary)
    lines.extend(
        f"{_escape_mrkdwn(_pr_label(pr, qualify=qualify))} — {_escape_mrkdwn(pr.summary)}" for pr in summary.prs
    )
    return "\n".join(lines) or "Merged PRs digest"


def _post_message(slack: SlackIntegration, digest_channel: DigestChannel, summary: DigestSummary) -> SlackResponse:
    # No unfurls: the summary text is LLM output over untrusted PR content, so a prompt-injected
    # URL must not make Slack's unfurler fetch an attacker's server from inside the workspace.
    return slack.client.chat_postMessage(
        channel=digest_channel.slack_channel_id,
        blocks=_build_blocks(summary),
        text=_build_fallback_text(summary),
        unfurl_links=False,
        unfurl_media=False,
    )


def _join_channel(slack: SlackIntegration, digest_channel: DigestChannel) -> str | None:
    """Join the channel so the retried post lands. Returns Slack's error code when it refused.

    A channel resolved by name match is one the app was never invited to, which is the normal state
    for an auto-provisioned row, so joining is what saves every team a manual ``/invite``. Tried
    rather than gated on the scope: ``conversations.join`` needs ``channels:join``, and whether an
    install granted it is not something the person who set up the digest can see or change. Slack
    answers ``missing_scope`` in under a second, and the caller turns that into an error naming the
    invite.

    ``already_in_channel`` counts as joined: two audiences can resolve to the same channel, so
    another worker may join between this one's failed post and its join, and treating that as a
    refusal would fail a digest whose retry would have gone through.
    """
    try:
        slack.client.conversations_join(channel=digest_channel.slack_channel_id)
    except SlackApiError as e:
        error = str(e.response.get("error") or "unknown_error")
        if error == "already_in_channel":
            return None
        logger.warning("stamphog_digest_join_failed", digest_channel_id=str(digest_channel.id), error=error)
        return error
    return None


def post_digest(team_id: int, digest_channel: DigestChannel, summary: DigestSummary) -> str | None:
    """Post the digest to the channel's Slack destination. Returns the message ts, or None."""
    integration = Integration.objects.filter(
        id=digest_channel.slack_integration_id, team_id=team_id, kind="slack"
    ).first()
    if integration is None:
        raise DigestSlackError(f"No slack integration {digest_channel.slack_integration_id} for team {team_id}")

    slack = SlackIntegration(integration)
    try:
        response = _post_message(slack, digest_channel, summary)
    except SlackApiError as e:
        if e.response.get("error") != "not_in_channel":
            raise
        # Retry once behind the join. A refusal names both Slack's reason and the fix: the run is what
        # a human reads, and neither "invite the app" nor why the join failed is derivable from a
        # raw Slack error code.
        join_error = _join_channel(slack, digest_channel)
        if join_error is not None:
            channel = digest_channel.slack_channel_name or digest_channel.slack_channel_id
            raise DigestSlackError(
                f"Couldn't post to #{channel}. PostHog isn't in the channel and couldn't join it: Slack said "
                f"{join_error}. Invite the app with /invite @PostHog."
            ) from e
        response = _post_message(slack, digest_channel, summary)

    ts = response.get("ts")
    return str(ts) if ts else None
