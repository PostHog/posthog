"""Review-thread I/O for the resolution stage, over GitHub's GraphQL API.

Thread resolution state (`isResolved` / `isOutdated`), thread node ids, and the resolve mutation are
GraphQL-only — REST exposes review comments flat, with no thread identity or state. Calls route
through the same gated egress transport as ReviewHog's REST layer (`/graphql` is classified into the
core rate budget by the egress limiter).

The work-list contract (CONTEXT.md — "Work-list"): unresolved review threads only, the thread is the
unit, outdated unresolved threads included, resolved threads never fetched back.
"""

import logging
from typing import Any

from pydantic import BaseModel, Field

from posthog.egress.github.transport import github_request, raise_if_github_rate_limited
from posthog.egress.limiter.policies import Priority

from products.review_hog.backend.reviewer.artefact_content import ThreadVerdictArtefact
from products.review_hog.backend.reviewer.tools.github_client import GITHUB_API_BASE, GitHubAPIError

logger = logging.getLogger(__name__)

_SOURCE = "review_hog"
_TIMEOUT = 30.0
_THREADS_PAGE_SIZE = 100
_COMMENTS_PER_THREAD = 50

# Source-rank tiers for triage ordering: humans first, ReviewHog's own findings next, other bots
# last (CONTEXT.md — "Comment-loading policy"). Rank never excludes a thread, it only orders work.
_RANK_HUMAN = 0
_RANK_REVIEW_HOG = 1
_RANK_OTHER_BOT = 2

# Hidden marker stamped on every ReviewHog inline finding comment (publish_review._format_issue_comment)
# so the resolution stage can recognize its own threads by content. Installation bot logins vary per
# deployment, so there is no stable login to match on; this marker is the reliable signal. Same
# HTML-comment style as the review-body / promo / status markers, invisible in rendered markdown.
REVIEW_HOG_FINDING_MARKER = "<!-- reviewhog:finding -->"


class ThreadComment(BaseModel):
    """One comment inside a review thread, as the resolution stage consumes it."""

    id: int | None = Field(default=None, description="GitHub databaseId; None for minimized/ghost comments.")
    author_login: str = ""
    # From GraphQL `author { __typename }` — authoritative, unlike login-suffix heuristics.
    author_is_bot: bool = False
    # OWNER / MEMBER / COLLABORATOR / CONTRIBUTOR / NONE … — feeds the trust weighting in the prompt.
    author_association: str = "NONE"
    body: str = ""
    created_at: str = ""
    url: str = ""


class ReviewThread(BaseModel):
    """One unresolved review thread — the resolution stage's unit of work."""

    thread_id: str  # GraphQL node id (PRRT_…) — drives the reply/resolve mutations.
    path: str = ""
    line: int | None = None
    is_outdated: bool = False
    comments: list[ThreadComment] = Field(default_factory=list)

    @property
    def first_comment(self) -> ThreadComment | None:
        return self.comments[0] if self.comments else None

    @property
    def author_login(self) -> str:
        first = self.first_comment
        return first.author_login if first else ""

    @property
    def author_is_bot(self) -> bool:
        first = self.first_comment
        return first.author_is_bot if first else False

    @property
    def latest_comment_id(self) -> int | None:
        """The newest comment's databaseId — the per-thread watermark verdicts are compared against."""
        return max((c.id for c in self.comments if c.id is not None), default=None)


def github_graphql_request(
    query: str,
    variables: dict[str, Any],
    *,
    token: str,
    installation_id: str | None = None,
) -> dict[str, Any]:
    """One gated, recorded GitHub GraphQL call; returns the `data` payload.

    GraphQL reports failures as a 200 with an `errors` array, so both transport-level non-2xx and
    in-body errors raise `GitHubAPIError`.
    """
    response = github_request(
        "POST",
        f"{GITHUB_API_BASE}/graphql",
        source=_SOURCE,
        headers={"Authorization": f"Bearer {token}"},
        installation_id=installation_id,
        # Same tier as ReviewHog's REST calls: automated, retried by Temporal, but devs do wait on it.
        priority=Priority.NORMAL,
        endpoint="/graphql",
        json={"query": query, "variables": variables},
        timeout=_TIMEOUT,
    )
    raise_if_github_rate_limited(response)
    if not response.ok:
        raise GitHubAPIError(
            f"GitHub GraphQL returned {response.status_code}: {response.text[:200]}",
            status=response.status_code,
        )
    body = response.json()
    if body.get("errors"):
        first = body["errors"][0]
        message = first.get("message", "unknown GraphQL error") if isinstance(first, dict) else str(first)
        raise GitHubAPIError(f"GitHub GraphQL error: {message}", status=response.status_code, api_message=message)
    return body.get("data") or {}


# Page sizes ride as GraphQL variables so the query document needs no string formatting.
_THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $cursor: String, $pageSize: Int!, $commentsPerThread: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: $pageSize, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          comments(first: $commentsPerThread) {
            nodes {
              databaseId
              url
              body
              createdAt
              authorAssociation
              author { login __typename }
            }
          }
        }
      }
    }
  }
}
"""


def _parse_thread(node: dict[str, Any]) -> ReviewThread:
    comments: list[ThreadComment] = []
    for comment in (node.get("comments") or {}).get("nodes") or []:
        if not isinstance(comment, dict):
            continue
        author = comment.get("author") or {}
        comments.append(
            ThreadComment(
                id=comment.get("databaseId"),
                author_login=author.get("login") or "",
                author_is_bot=author.get("__typename") == "Bot",
                author_association=comment.get("authorAssociation") or "NONE",
                body=comment.get("body") or "",
                created_at=comment.get("createdAt") or "",
                url=comment.get("url") or "",
            )
        )
    return ReviewThread(
        thread_id=node["id"],
        path=node.get("path") or "",
        line=node.get("line"),
        is_outdated=bool(node.get("isOutdated")),
        comments=comments,
    )


def fetch_unresolved_threads(
    *,
    token: str,
    owner: str,
    repo: str,
    pr_number: int,
    installation_id: str | None = None,
) -> list[ReviewThread]:
    """Every unresolved review thread on the PR (outdated included), oldest page first."""
    threads: list[ReviewThread] = []
    cursor: str | None = None
    while True:
        data = github_graphql_request(
            _THREADS_QUERY,
            {
                "owner": owner,
                "name": repo,
                "number": pr_number,
                "cursor": cursor,
                "pageSize": _THREADS_PAGE_SIZE,
                "commentsPerThread": _COMMENTS_PER_THREAD,
            },
            token=token,
            installation_id=installation_id,
        )
        pull_request = ((data.get("repository") or {}).get("pullRequest")) or {}
        connection = pull_request.get("reviewThreads") or {}
        for node in connection.get("nodes") or []:
            if not isinstance(node, dict) or node.get("isResolved"):
                continue
            threads.append(_parse_thread(node))
        page_info = connection.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            return threads
        cursor = page_info.get("endCursor")


def reply_to_thread(
    *,
    token: str,
    thread_id: str,
    body: str,
    installation_id: str | None = None,
) -> tuple[int | None, str | None]:
    """Post a reply on a review thread; returns the new comment's (databaseId, url)."""
    data = github_graphql_request(
        """
        mutation($threadId: ID!, $body: String!) {
          addPullRequestReviewThreadReply(input: {pullRequestReviewThreadId: $threadId, body: $body}) {
            comment { databaseId url }
          }
        }
        """,
        {"threadId": thread_id, "body": body},
        token=token,
        installation_id=installation_id,
    )
    comment = ((data.get("addPullRequestReviewThreadReply") or {}).get("comment")) or {}
    return comment.get("databaseId"), comment.get("url")


def resolve_thread(*, token: str, thread_id: str, installation_id: str | None = None) -> bool:
    """Resolve a review thread; returns GitHub's resulting `isResolved`."""
    data = github_graphql_request(
        """
        mutation($threadId: ID!) {
          resolveReviewThread(input: {threadId: $threadId}) {
            thread { isResolved }
          }
        }
        """,
        {"threadId": thread_id},
        token=token,
        installation_id=installation_id,
    )
    thread = ((data.get("resolveReviewThread") or {}).get("thread")) or {}
    return bool(thread.get("isResolved"))


def _source_rank(thread: ReviewThread) -> int:
    """Triage-order tier for a thread by who opened it: human, ReviewHog itself, or another bot.

    ReviewHog's own inline comments carry a hidden marker (`REVIEW_HOG_FINDING_MARKER`) stamped at
    publish time; a bot thread whose opening comment contains it is one of ours. Installation bot
    logins vary per deployment, so there is no stable login to match on — the marker is the reliable
    signal. A miss only demotes the thread to the other-bot tier; it is still triaged.
    """
    first = thread.first_comment
    if first is None or not first.author_is_bot:
        return _RANK_HUMAN
    return _RANK_REVIEW_HOG if REVIEW_HOG_FINDING_MARKER in first.body else _RANK_OTHER_BOT


def order_threads(threads: list[ReviewThread]) -> list[ReviewThread]:
    """Priority order for triage: humans → ReviewHog → other bots, oldest first within each tier.

    Order matters beyond politeness: turns share one working tree, so when two asks conflict the
    earlier one wins — this makes that the human's.
    """
    return sorted(threads, key=lambda t: (_source_rank(t), (t.first_comment.created_at if t.first_comment else "")))


class ThreadAction:
    """Deterministic pre-filter verdict for one thread against its persisted resolution verdict."""

    TRIAGE = "triage"  # no verdict yet, or new comments since it — a resolution turn is needed
    SIDE_EFFECTS = "side_effects"  # verdict current but its reply never posted — redo GitHub writes only
    SKIP = "skip"  # verdict current and delivered; nothing to do


def should_resolve(verdict: ThreadVerdictArtefact) -> bool:
    """The resolution etiquette's resolve gate: bot-authored threads on terminal outcomes only.

    Human threads are never resolved by the stage — the human keeps the final word on their own
    thread — and ESCALATE never resolves, for any author (see CONTEXT.md — "Resolution etiquette").
    """
    return verdict.author_is_bot and verdict.outcome != "escalate"


def classify_thread(thread: ReviewThread, verdict: ThreadVerdictArtefact | None) -> str:
    """The deterministic pre-filter (no LLM): does this thread need a turn, side effects, or nothing?

    Any comment newer than the verdict's watermark re-opens triage — pushback on a WON'T FIX gets a
    fresh assessment with the pushback in context. The watermark is the newest comment databaseId
    known at verdict time (our own posted reply once it lands), so the stage's replies don't
    re-trigger it. A verdict whose GitHub writes only partially landed (reply missing, or a due
    resolve missing) is redelivered without a new LLM turn.
    """
    if verdict is None:
        return ThreadAction.TRIAGE
    latest = thread.latest_comment_id
    if latest is not None and (verdict.latest_comment_id is None or latest > verdict.latest_comment_id):
        return ThreadAction.TRIAGE
    if not verdict.reply_posted:
        return ThreadAction.SIDE_EFFECTS
    if should_resolve(verdict) and not verdict.resolved:
        return ThreadAction.SIDE_EFFECTS
    return ThreadAction.SKIP
