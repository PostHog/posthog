"""Post a merged-PR digest to Slack via a team's Slack integration.

Renders the summary as Block Kit and posts it with a plain-text fallback for notifications. Raises
``DigestSlackError`` when the stored integration can't be resolved for the team so the caller can
record the run as failed and retry the PRs tomorrow.

Shape: one line per change, then a footer. Every part that is not a change was cut, because a daily
bot post competes with the channel it lands in and loses on anything a reader has already read once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from slack_sdk.errors import SlackApiError
from slack_sdk.web import SlackResponse

from posthog.models.integration import Integration, SlackIntegration

if TYPE_CHECKING:
    from ..models import DigestChannel
    from .digest import DigestSummary

logger = structlog.get_logger(__name__)

# Slack rejects a section whose mrkdwn text exceeds 3000 chars, and the failure path unlinks the
# claimed PRs — an oversized LLM summary would make every daily retry fail the same way forever.
_MAX_SECTION_CHARS = 2900


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class DigestSlackError(Exception):
    """The digest could not be posted to Slack (integration missing, mismatched, or API failure)."""


def _escape_mrkdwn(text: str) -> str:
    """Neutralize Slack mrkdwn control characters in attacker-controlled text.

    Model-generated summaries are written over contributor-authored PR text. Escaping
    ``&``/``<``/``>`` stops a merged PR from smuggling ``<!channel>`` mentions or breaking out of a link
    into the digest channel; Slack renders the escaped entities back as the literal characters.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _link(url: str, label: str) -> str:
    # url is trusted (built from the GitHub PR URL); the label is untrusted, so escape it and drop the
    # `|` that would otherwise split the link syntax. Clipping happens inside the label rather than
    # over the finished string: the label is now the whole line, so trimming the tail off the assembled
    # link would take the closing `>` with it and leave Slack rendering raw markup instead of a link.
    body = _clip(_escape_mrkdwn(label).replace("|", "/"), _MAX_SECTION_CHARS - len(url) - len("<|>"))
    return f"<{url}|{body}>"


def _scope_line(shown: int, considered: int) -> str:
    """The one line that stops a short digest from reading as everything that happened.

    A reader who sees two changes and nothing else concludes two things merged. Naming the
    denominator says more merged than this. It stops there and makes no claim about what was left
    out, because nothing here can back one up: the digest only ever sees merges stamphog approved,
    so even the denominator is a floor rather than the day's total.

    It sits in the footer rather than the lead. The same sentence every morning is chrome the eye
    learns to skip, and putting chrome first spends the only line the digest gets to earn attention.
    """
    if considered > shown:
        return f"{shown} of {considered} stamphog-approved merges."
    return f"{shown} stamphog-approved {'merge' if shown == 1 else 'merges'}."


def _build_blocks(summary: DigestSummary) -> list[dict]:
    """One section per change, then a footer. No header and no intro.

    The header said "Merged PRs digest" to people who could see it came from stamphog, in a channel
    that gets one daily, and the intro was a model-written sentence about a list printed directly
    below it. Both cost a reader their first line, which is the one that decides whether the rest
    gets read, so the first line is now the first change.
    """
    blocks: list[dict] = []
    for pr in summary.prs:
        # The sentence is the link, and it is the whole line. A leading "#412" makes a reader parse
        # an identifier before they reach what changed, and a trailing author repeats down the
        # column on the common day where one person did most of the work. Both are on the PR, one
        # click away, for the few readers who want them.
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": _link(pr.url, pr.summary)},
            }
        )
    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": _scope_line(len(summary.prs), summary.considered)}],
        }
    )
    return blocks


def _build_fallback_text(summary: DigestSummary) -> str:
    """Plain text for the notification preview and for clients that ignore blocks.

    Leads with the first change, not with a title: the preview is what a reader sees on their lock
    screen or in the channel list, and "Merged PRs digest" there tells them nothing they can act on.
    """
    # The top-level `text` fallback is parsed for mentions too, so escape it the same way.
    lines = [_escape_mrkdwn(pr.summary) for pr in summary.prs]
    return "\n".join(lines) or "No merged PRs worth a mention."


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
