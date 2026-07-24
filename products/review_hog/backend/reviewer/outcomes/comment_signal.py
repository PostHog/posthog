"""The human-engagement signal: did a finding's inline comment get a reply or a reaction?

ReviewHog's published comments lead with ``### {finding.title}`` and anchor to the finding's file, so
a finding maps to its posted comment exactly by (path, title) — no stored comment id, and robust to
line drift after review (the match is on body content, not position). The one
``GET /pulls/{n}/comments`` list carries both an ``in_reply_to_id`` per comment and a ``reactions``
summary, so replies and reactions are read without any extra call or GraphQL.
"""

from typing import Any

from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding


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
    """`"comment_reaction"` / `"comment_reply"` if the finding's thread was engaged, else None.

    A reaction on the comment or a non-bot comment replying to it (``in_reply_to_id``) counts as a
    human responding to the finding; bot replies (other review/CI apps chiming in) don't. The
    ``reactions`` summary carries no actor, so a bot reaction would count — accepted: resolving actors
    costs an extra call per comment and bots don't react to inline review comments in practice.
    Reaction wins when both are present — it's the cheaper, unambiguous signal (a reply can be the
    author asking a clarifying question, still engagement, so both map to `reacted`).
    """
    if (comment.get("reactions") or {}).get("total_count", 0) > 0:
        return "comment_reaction"
    comment_id = comment.get("id")
    if comment_id is not None and any(
        rc.get("in_reply_to_id") == comment_id and not _is_bot(rc.get("user")) for rc in review_comments
    ):
        return "comment_reply"
    return None
