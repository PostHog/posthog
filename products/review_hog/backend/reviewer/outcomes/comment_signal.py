"""The engagement signal: did a finding's inline comment get a reply or a reaction?

ReviewHog's published comments lead with a heading that holds ``finding.title`` and anchor to the
finding's file, so a finding maps to its posted comment exactly by (path, title) — no stored comment id, and robust to
line drift after review (the match is on body content, not position). The one
``GET /pulls/{n}/comments`` list carries an ``in_reply_to_id`` per comment, so replies need no extra
call. Its ``reactions`` summary counts reactions but names nobody, so a comment with a reaction costs
one more read to see who left it (``fetch_comment_reactions``).
"""

from typing import Any

from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding
from products.review_hog.backend.reviewer.constants import (
    LEGACY_FLASH_MODE_MESSAGE_PREFIX,
    REPORTED_LEVELS,
    finding_heading,
)
from products.review_hog.backend.reviewer.tools.github_client import is_app_bot_author


def _is_bot(user: dict[str, Any] | None) -> bool:
    login = (user or {}).get("login") or ""
    return (user or {}).get("type") == "Bot" or login.endswith("[bot]")


def find_finding_comment(
    *, finding: ReviewIssueFinding, review_comments: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """The review comment ReviewHog posted for ``finding``, matched by path + exact heading, or None.

    The whole first line must equal ``**P{n} · {title}**`` for any P level, or ``### {title}`` for
    comments published before the P-level heading. A prefix match would pair "Foo" with a comment
    headed "Foobar". The level is not checked, because a validator override can change it after
    publish. First match wins if two findings in a file share a title (rare); the outcome is the same
    engaged/not signal either way.
    """
    headings = {f"### {finding.title}"} | {finding_heading(finding.title, level) for level in REPORTED_LEVELS}
    for comment in review_comments:
        if comment.get("path") != finding.file:
            continue
        # Flash comments posted before reviewhog-flash-1-1 open with the flash banner line, so the
        # banner is removed before the title check.
        body = (comment.get("body") or "").removeprefix(LEGACY_FLASH_MODE_MESSAGE_PREFIX)
        first_line = body.split("\n", 1)[0].rstrip()
        if first_line in headings:
            return comment
    return None


def engagement_method(
    *, comment: dict[str, Any], review_comments: list[dict[str, Any]], reactions: list[dict[str, Any]]
) -> str | None:
    """How the finding's thread was engaged, or None if it wasn't. All results map to `reacted`.

    Engagement means *someone responded*, not specifically a human: a reply from another agent (a
    reviewer's own bot answering on their behalf, a fixer agent) is a response to the finding, and the
    actor is recorded in the method rather than filtered out. `comment_reply` is a human, and
    `comment_reply_agent` is any other bot, so a query that wants strictly-human engagement can select
    for it while the coarse `reacted` outcome keeps counting both.

    ReviewHog's own replies are the exception and never count: it publishes the finding comment, so
    treating its own follow-up as engagement would let the feature grade its own homework. A fix it
    lands itself still shows up, as a commit in the post-review compare that the judge rules on —
    engagement is not where that belongs. Note `is_app_bot_author` can only single out our bot when
    `REVIEWHOG_GITHUB_BOT_LOGIN` is set. Unset, local runs fall back to "any bot", which ignores
    every bot reply, and production trusts no bot, which counts our own replies as agent replies.

    A human reply beats an agent one when both are present, and a reaction beats both: it is the
    cheaper, unambiguous signal. ``reactions`` are the comment's reactions with their actors, and the
    same rule applies to them: ReviewHog's own never count. The resolution stage puts a 👀 on every
    thread it queues, so counting it would mark each of those findings ``reacted`` and keep the judge
    from ruling on the fix that followed.
    """
    if any(not is_app_bot_author(reaction.get("user")) for reaction in reactions):
        return "comment_reaction"
    comment_id = comment.get("id")
    if comment_id is None:
        return None
    replies = [rc for rc in review_comments if rc.get("in_reply_to_id") == comment_id]
    if any(not _is_bot(rc.get("user")) for rc in replies):
        return "comment_reply"
    if any(not is_app_bot_author(rc.get("user")) for rc in replies):
        return "comment_reply_agent"
    return None
