"""Post a merged-PR digest to Slack via a team's Slack integration.

Renders the summary as Block Kit and posts it with a plain-text fallback for notifications. Raises
``DigestSlackError`` when the stored integration can't be resolved for the team so the caller can
record the run as failed and retry the PRs tomorrow.

Shape: the channel gets one lead (the model's headline, or the scope line when it wrote none) and a
footer. The per-change lines go in a thread under it. A daily bot post competes with the channel it
lands in, so it spends one line there and keeps the rest where a reader can open it by choice.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from slack_sdk.errors import SlackApiError
from slack_sdk.web import SlackResponse

from posthog.models.integration import Integration, SlackIntegration

if TYPE_CHECKING:
    from .channel_resolution import Destination
    from .digest import DigestSummary

logger = structlog.get_logger(__name__)

# Slack rejects a section whose mrkdwn text exceeds 3000 chars, and the failure path unlinks the
# claimed PRs — an oversized LLM summary would make every daily retry fail the same way forever.
_MAX_SECTION_CHARS = 2900


# What the digest is, and how to answer it. Every reader sees this line, so it carries the two things
# that are not in any single digest: that the feature is still being tuned, and where to say so.
_FOOTER_INVITE = "React with :+1: or :-1:, or reply with feedback."
_BETA_LABEL = "Beta"

# The first line of the thread. It names whose judgment picked these changes, and it claims nothing
# about completeness. The line it replaced said "Full list in the thread", which readers reasonably
# read as the full list: the thread carries what cleared the bar, never every merge of the day.
_THREAD_LEAD = "Changes Stamphog thinks your team should know about:"


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
        return f"{shown} of {considered} Stamphog-approved merges."
    return f"{shown} Stamphog-approved {'merge' if shown == 1 else 'merges'}."


def _lead_text(summary: DigestSummary) -> str:
    """The one line the channel gets: the model's headline, or the scope line when it wrote none.

    The headline is model output over untrusted PR content, so it is escaped and clipped like any
    other summary text. The scope line is built from counts and is safe as it stands.
    """
    if summary.headline:
        return _clip(_escape_mrkdwn(summary.headline), _MAX_SECTION_CHARS)
    return _scope_line(len(summary.prs), summary.considered)


def _footer_text(summary: DigestSummary) -> str:
    """The context line under the lead.

    The scope line appears here only when the lead is a headline, because a digest with no headline
    already leads with it. Printing it twice would make a two-line post state its own count twice.
    """
    if not summary.headline:
        return f"{_BETA_LABEL} · {_FOOTER_INVITE}"
    return f"{_BETA_LABEL} · {_scope_line(len(summary.prs), summary.considered)}\n{_FOOTER_INVITE}"


def _lead_blocks(summary: DigestSummary) -> list[dict]:
    """What lands in the channel: one lead, then the footer. The changes go in the thread."""
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": _lead_text(summary)}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": _footer_text(summary)}]},
    ]


def _detail_blocks(summary: DigestSummary) -> list[dict]:
    """The lead line, then one section per change, for the thread under the channel post."""
    # The sentence is the link, and it is the whole line. A leading "#412" makes a reader parse an
    # identifier before they reach what changed, and a trailing author repeats down the column on
    # the common day where one person did most of the work. Both are on the PR, one click away, for
    # the few readers who want them.
    return [
        {"type": "context", "elements": [{"type": "mrkdwn", "text": _THREAD_LEAD}]},
        *({"type": "section", "text": {"type": "mrkdwn", "text": _link(pr.url, pr.summary)}} for pr in summary.prs),
    ]


def _build_fallback_text(summary: DigestSummary) -> str:
    """Plain text for the thread's notification preview and for clients that ignore blocks.

    The lead line stays out of it. A notification shows the first few words, and spending them on
    the same sentence every morning pushes the change itself out of view.
    """
    # The top-level `text` fallback is parsed for mentions too, so escape it the same way.
    lines = [_escape_mrkdwn(pr.summary) for pr in summary.prs]
    return "\n".join(lines) or "No merged PRs worth a mention."


def _post_message(
    slack: SlackIntegration,
    destination: Destination,
    blocks: list[dict],
    text: str,
    thread_ts: str | None = None,
) -> SlackResponse:
    # No unfurls: the summary text is LLM output over untrusted PR content, so a prompt-injected
    # URL must not make Slack's unfurler fetch an attacker's server from inside the workspace.
    return slack.client.chat_postMessage(
        channel=destination.channel_id,
        blocks=blocks,
        text=text,
        thread_ts=thread_ts,
        unfurl_links=False,
        unfurl_media=False,
    )


def post_digest_details(team_id: int, destination: Destination, summary: DigestSummary, thread_ts: str | None) -> None:
    """Post the per-change lines under the lead. Never raises.

    The caller records the lead as posted before it calls this, and it consumes the claimed audience
    rows on that record. A failure here must not undo that: it would release those rows and send the
    same lead again tomorrow, so the channel would carry the digest twice. Losing the thread costs
    one day of detail for changes the reader can still find on GitHub.

    Skipped when Slack returned no ts. Without a parent to hang it on, the reply lands in the
    channel as a second top-level post, which is the noise the thread exists to remove.
    """
    if not thread_ts or not summary.prs:
        return
    integration = Integration.objects.filter(id=destination.slack_integration_id, team_id=team_id, kind="slack").first()
    if integration is None:
        return
    try:
        _post_message(
            SlackIntegration(integration),
            destination,
            _detail_blocks(summary),
            _build_fallback_text(summary),
            thread_ts,
        )
    except Exception as e:
        # Every failure class, not only SlackApiError. A transport error raised here propagates into
        # the caller's failure path and undoes a digest that Slack already accepted.
        logger.warning("stamphog_digest_thread_post_failed", slack_channel_id=destination.channel_id, error=str(e))


def _join_channel(slack: SlackIntegration, destination: Destination) -> str | None:
    """Join the channel so the retried post lands. Returns Slack's error code when it refused.

    A channel resolved by name match is one the app was never invited to, which is the normal state
    for a destination nobody set up by hand, so joining is what saves every team a manual
    ``/invite``. Tried
    rather than gated on the scope: ``conversations.join`` needs ``channels:join``, and whether an
    install granted it is not something the person who set up the digest can see or change. Slack
    answers ``missing_scope`` in under a second, and the caller turns that into an error naming the
    invite.

    ``already_in_channel`` counts as joined: two audiences can resolve to the same channel, so
    another worker may join between this one's failed post and its join, and treating that as a
    refusal would fail a digest whose retry would have gone through.
    """
    try:
        slack.client.conversations_join(channel=destination.channel_id)
    except SlackApiError as e:
        error = str(e.response.get("error") or "unknown_error")
        if error == "already_in_channel":
            return None
        logger.warning("stamphog_digest_join_failed", slack_channel_id=destination.channel_id, error=error)
        return error
    return None


def post_digest_lead(team_id: int, destination: Destination, summary: DigestSummary) -> str | None:
    """Post the channel-level message. Returns its ts, or None.

    This message decides whether the digest was delivered. The caller records the ts it returns
    before it calls post_digest_details, so a worker that dies between the two leaves a run the
    sweeper finalizes. Without that order, a Slack-accepted digest reads as unposted, and the next
    run releases its merges and sends the same lead again.
    """
    integration = Integration.objects.filter(id=destination.slack_integration_id, team_id=team_id, kind="slack").first()
    if integration is None:
        raise DigestSlackError(f"No slack integration {destination.slack_integration_id} for team {team_id}")

    slack = SlackIntegration(integration)
    lead_blocks = _lead_blocks(summary)
    lead_text = _lead_text(summary)
    try:
        response = _post_message(slack, destination, lead_blocks, lead_text)
    except SlackApiError as e:
        if e.response.get("error") != "not_in_channel":
            raise
        # Retry once behind the join. A refusal names both Slack's reason and the fix: the run is what
        # a human reads, and neither "invite the app" nor why the join failed is derivable from a
        # raw Slack error code.
        join_error = _join_channel(slack, destination)
        if join_error is not None:
            channel = destination.channel_name or destination.channel_id
            raise DigestSlackError(
                f"Couldn't post to #{channel}. PostHog isn't in the channel and couldn't join it: Slack said "
                f"{join_error}. Invite the app with /invite @PostHog."
            ) from e
        response = _post_message(slack, destination, lead_blocks, lead_text)

    ts = response.get("ts")
    return str(ts) if ts else None
