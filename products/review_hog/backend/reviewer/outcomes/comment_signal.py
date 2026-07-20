"""The human-engagement signal: did a finding's inline comment get a reply or a reaction?

ReviewHog's published comments lead with ``### {finding.title}`` and anchor to the finding's file, so
a finding maps to its posted comment exactly by (path, title) — no stored comment id, and robust to
line drift after review (the match is on body content, not position). The one
``GET /pulls/{n}/comments`` list carries both an ``in_reply_to_id`` per comment and a ``reactions``
summary, so replies and reactions are read without any extra call or GraphQL.
"""

from typing import Any

from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding


def find_finding_comment(
    *, finding: ReviewIssueFinding, review_comments: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """The review comment ReviewHog posted for ``finding``, matched by path + title, or None.

    First match wins if two findings in a file share a title (rare); the outcome is the same
    engaged/not signal either way.
    """
    title_prefix = f"### {finding.title}"
    for comment in review_comments:
        if comment.get("path") == finding.file and (comment.get("body") or "").startswith(title_prefix):
            return comment
    return None


def engagement_method(*, comment: dict[str, Any], review_comments: list[dict[str, Any]]) -> str | None:
    """`"comment_reaction"` / `"comment_reply"` if the finding's thread was engaged, else None.

    A reaction on the comment or any comment replying to it (``in_reply_to_id``) counts as a human
    responding to the finding. Reaction wins when both are present — it's the cheaper, unambiguous
    signal (a reply can be the author asking a clarifying question, still engagement, so both map to
    `reacted`).
    """
    if (comment.get("reactions") or {}).get("total_count", 0) > 0:
        return "comment_reaction"
    comment_id = comment.get("id")
    if comment_id is not None and any(rc.get("in_reply_to_id") == comment_id for rc in review_comments):
        return "comment_reply"
    return None
