"""The engagement signal: did a finding's inline comment get a reply or a reaction?

ReviewHog's published comments lead with ``### {finding.title}`` and anchor to the finding's file, so
a finding maps to its posted comment exactly by (path, title) — no stored comment id, and robust to
line drift after review (the match is on body content, not position). The one
``GET /pulls/{n}/comments`` list carries both an ``in_reply_to_id`` per comment and a ``reactions``
summary, so replies and reactions are read without any extra call or GraphQL.
"""

from typing import Any

from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding
from products.review_hog.backend.reviewer.tools.github_client import is_app_bot_author


def _is_bot(user: dict[str, Any] | None) -> bool:
    login = (user or {}).get("login") or ""
    return (user or {}).get("type") == "Bot" or login.endswith("[bot]")


def find_finding_comment(
    *, finding: ReviewIssueFinding, review_comments: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """The review comment ReviewHog posted for ``finding``, matched by path + exact heading, or None.

    The whole first line must equal ``### {title}`` — a prefix match would pair "Foo" with a comment
    headed "### Foobar". First match wins if two findings in a file share a title (rare); the outcome
    is the same engaged/not signal either way.
    """
    heading = f"### {finding.title}"
    for comment in review_comments:
        if comment.get("path") != finding.file:
            continue
        first_line = (comment.get("body") or "").split("\n", 1)[0].rstrip()
        if first_line == heading:
            return comment
    return None


def engagement_method(*, comment: dict[str, Any], review_comments: list[dict[str, Any]]) -> str | None:
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
    `REVIEWHOG_GITHUB_BOT_LOGIN` is set; unset it fails open to "any bot", which degrades this to the
    old behavior of ignoring every bot reply.

    A human reply beats an agent one when both are present, and a reaction beats both: it is the
    cheaper, unambiguous signal. The ``reactions`` summary carries no actor, so a bot reaction counts
    as a reaction — accepted, and now consistent with replies rather than at odds with them.
    """
    if (comment.get("reactions") or {}).get("total_count", 0) > 0:
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
