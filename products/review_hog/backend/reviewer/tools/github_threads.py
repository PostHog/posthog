"""Review-thread I/O for the resolution stage, over GitHub's GraphQL API.

Thread resolution state (`isResolved` / `isOutdated`), thread node ids, and the resolve mutation are
GraphQL-only — REST exposes review comments flat, with no thread identity or state. Calls route
through the same gated egress transport as ReviewHog's REST layer (`/graphql` is classified into the
core rate budget by the egress limiter).

The work-list contract (CONTEXT.md — "Work-list"): unresolved review threads only, the thread is the
unit, outdated unresolved threads included, resolved threads never fetched back.
"""

import time
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from posthog.egress.github.transport import GitHubRateLimitError, github_request, raise_if_github_rate_limited
from posthog.egress.limiter.policies import Priority

from products.review_hog.backend.reviewer.artefact_content import ThreadVerdictArtefact
from products.review_hog.backend.reviewer.tools.github_client import (
    GITHUB_API_BASE,
    GitHubAPIError,
    github_api_request,
    is_app_bot_author,
)

logger = logging.getLogger(__name__)

_SOURCE = "review_hog"
_TIMEOUT = 30.0
_THREADS_PAGE_SIZE = 100
_COMMENTS_PER_THREAD = 50
# Tail-paging backstop for absurdly chatty threads: 20 pages x 50 comments = 1000. Past that we
# fail the fetch rather than silently truncate — a truncated tail would freeze the watermark below
# the thread's real newest comment and the thread would never re-open to triage (stamphog's
# github_client.py documents the same trade: comment 51 could be a maintainer's hold).
_MAX_COMMENT_PAGES = 20
# Same fail-closed posture for the outer thread list: 20 pages x 100 threads = 2000. A PR past that
# is bot spam or pathology; refuse loudly instead of paging on (stamphog caps the identical query).
_MAX_THREAD_PAGES = 20

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
    # GraphQL node id (PRRC_…) — the addReaction mutation's subject; empty for ghost comments.
    node_id: str = ""
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
        if any(isinstance(e, dict) and e.get("type") == "RATE_LIMITED" for e in body["errors"]):
            # GraphQL's primary rate limit is a 200 whose errors carry type RATE_LIMITED — invisible
            # to raise_if_github_rate_limited, which only inspects 429/403 responses.
            try:
                reset_at: int | None = int(response.headers.get("x-ratelimit-reset", ""))
            except (ValueError, TypeError):
                reset_at = None
            retry_after = max(1, reset_at - int(time.time())) if reset_at is not None else 60
            raise GitHubRateLimitError(
                f"GitHub GraphQL rate limit exceeded (resets at {reset_at})",
                reset_at=reset_at,
                retry_after=retry_after,
            )
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
          originalLine
          comments(first: $commentsPerThread) {
            pageInfo { hasNextPage endCursor }
            nodes {
              id
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

# GitHub returns thread comments oldest-first with no orderBy, so a capped first page drops the
# NEWEST activity. Threads whose inner connection overflows get their tail paged via this query.
_THREAD_COMMENTS_QUERY = """
query($id: ID!, $cursor: String, $commentsPerThread: Int!) {
  node(id: $id) {
    ... on PullRequestReviewThread {
      comments(first: $commentsPerThread, after: $cursor) {
        pageInfo { hasNextPage endCursor }
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
"""


def _parse_comments(nodes: list[Any]) -> list[ThreadComment]:
    comments: list[ThreadComment] = []
    for comment in nodes:
        if not isinstance(comment, dict):
            continue
        author = comment.get("author") or {}
        comments.append(
            ThreadComment(
                id=comment.get("databaseId"),
                node_id=comment.get("id") or "",
                author_login=author.get("login") or "",
                author_is_bot=author.get("__typename") == "Bot",
                author_association=comment.get("authorAssociation") or "NONE",
                body=comment.get("body") or "",
                created_at=comment.get("createdAt") or "",
                url=comment.get("url") or "",
            )
        )
    return comments


def _fetch_comment_tail(
    *,
    thread_id: str,
    cursor: str | None,
    token: str,
    installation_id: str | None,
) -> list[ThreadComment]:
    """Comments past the first page of a thread's inner connection, oldest-first."""
    comments: list[ThreadComment] = []
    for _page in range(_MAX_COMMENT_PAGES):
        data = github_graphql_request(
            _THREAD_COMMENTS_QUERY,
            {"id": thread_id, "cursor": cursor, "commentsPerThread": _COMMENTS_PER_THREAD},
            token=token,
            installation_id=installation_id,
        )
        connection = (data.get("node") or {}).get("comments") or {}
        comments.extend(_parse_comments(connection.get("nodes") or []))
        page_info = connection.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            return comments
        cursor = page_info.get("endCursor")
    # status=0: a client-side refusal, no HTTP exchange failed.
    raise GitHubAPIError(
        f"Thread {thread_id} has more than {_MAX_COMMENT_PAGES * _COMMENTS_PER_THREAD} comments", status=0
    )


def _parse_thread(node: dict[str, Any]) -> ReviewThread:
    comments = _parse_comments((node.get("comments") or {}).get("nodes") or [])
    return ReviewThread(
        thread_id=node["id"],
        path=node.get("path") or "",
        # GitHub nulls `line` once the code under the thread drifts; the pre-drift anchor
        # (`originalLine`) still beats none, and `is_outdated` flags it as possibly moved.
        line=node.get("line") if node.get("line") is not None else node.get("originalLine"),
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
    for _page in range(_MAX_THREAD_PAGES):
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
            thread = _parse_thread(node)
            comment_page = ((node.get("comments") or {}).get("pageInfo")) or {}
            if comment_page.get("hasNextPage"):
                # The inner connection overflowed, so the newest comments (and the true watermark)
                # are missing: page the tail in before the thread reaches triage.
                thread.comments.extend(
                    _fetch_comment_tail(
                        thread_id=thread.thread_id,
                        cursor=comment_page.get("endCursor"),
                        token=token,
                        installation_id=installation_id,
                    )
                )
            threads.append(thread)
        page_info = connection.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            return threads
        cursor = page_info.get("endCursor")
    raise GitHubAPIError(
        f"PR {owner}/{repo}#{pr_number} has more than {_MAX_THREAD_PAGES * _THREADS_PAGE_SIZE} review threads",
        status=0,
    )


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


def add_eyes_reaction(*, token: str, subject_id: str, installation_id: str | None = None) -> None:
    """Add a 👀 reaction to a comment (by GraphQL node id) — the "queued for this run" marker.

    Reactions send no notifications, and GitHub treats a repeat addReaction as a no-op, so a
    retried prepare step never stacks duplicates. The reaction is deliberately never removed:
    removal would double the API calls for no real gain (see DECISIONS.md — resolution-stage
    visibility).
    """
    github_graphql_request(
        """
        mutation($subjectId: ID!) {
          addReaction(input: {subjectId: $subjectId, content: EYES}) {
            reaction { content }
          }
        }
        """,
        {"subjectId": subject_id},
        token=token,
        installation_id=installation_id,
    )


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


# Deterministic backstop behind the prompt's <hard_limits>: paths a resolution fix commit may
# never touch on comment say-so. The prompt is the first line of defense; this gates DELIVERY —
# a violating commit is never linked or auto-resolved, and the reply flags it for a human.
# Security-sensitive *code* (auth, secrets, crypto) stays prompt-judged: it isn't path-derivable.
_RESTRICTED_PATH_PREFIXES = (".github/",)
_RESTRICTED_BASENAMES = frozenset(
    {
        "CODEOWNERS",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "pyproject.toml",
        "uv.lock",
        "requirements.txt",
        "requirements.in",
        "Cargo.toml",
        "Cargo.lock",
        "go.mod",
        "go.sum",
        "Gemfile",
        "Gemfile.lock",
    }
)


def is_restricted_fix_path(path: str) -> bool:
    normalized = path.lstrip("/")
    if normalized.startswith(_RESTRICTED_PATH_PREFIXES):
        return True
    return normalized.rsplit("/", 1)[-1] in _RESTRICTED_BASENAMES


@dataclass(frozen=True, kw_only=True)
class FixCommitInspection:
    """What one `GET /commits/{sha}` says about a claimed fix commit."""

    restricted_paths: list[str]
    # Authored by OUR app bot with a GitHub-verified signature. `commit_on_branch` proves the SHA
    # is on the branch, but "on the branch" includes every ancestor — without this gate a steered
    # turn could echo some human's old clean commit and have every check inspect the wrong one.
    provenance_ok: bool


def inspect_fix_commit(
    *, token: str, owner: str, repo: str, sha: str, installation_id: str | None = None
) -> FixCommitInspection:
    """Restricted paths the commit touches (empty = clean) plus its provenance, in one API call.

    Fails closed on GitHub's 300-file cap: a files list that may be truncated reports the commit as
    unverifiable rather than clean — a comment-driven fix that big deserves human eyes anyway.
    Provenance: signed-commit fixes are authored as the app's bot (`is_app_bot_author`, fail-open on
    login when `REVIEWHOG_GITHUB_BOT_LOGIN` is unset) and carry a verified web-flow signature; a
    reachable SHA failing either is not provably this run's fix. The residual — echoing one of the
    bot's own earlier commits — stays with the recorded session-provenance follow-up.
    """
    response = github_api_request(
        "GET",
        f"/repos/{owner}/{repo}/commits/{sha}",
        token=token,
        endpoint="/repos/{owner}/{repo}/commits/{ref}",
        installation_id=installation_id,
    )
    payload = response.json()
    verification = (payload.get("commit") or {}).get("verification") or {}
    provenance_ok = bool(verification.get("verified")) and is_app_bot_author(payload.get("author"))
    files = payload.get("files") or []
    # A rename is ONE entry with filename=new path and previous_filename=old path, so both sides
    # must be checked: renaming .github/workflows/x.yml out of place must still flag as restricted.
    hits = [
        path
        for f in files
        for path in (f.get("filename"), f.get("previous_filename"))
        if path and is_restricted_fix_path(path)
    ]
    if len(files) >= 300 and not hits:
        hits = ["(files list truncated at 300; cannot verify)"]
    return FixCommitInspection(restricted_paths=hits, provenance_ok=provenance_ok)


def commit_on_branch(
    *, token: str, owner: str, repo: str, sha: str, branch: str, installation_id: str | None = None
) -> bool:
    """Whether `sha` exists and is reachable from the current tip of `branch`.

    Guards FIXED delivery: `commit_sha` is the model's echo, so it is verified server-side before it
    becomes a public "Fix commit" link or auto-resolves a thread. Comparing against the branch NAME
    makes GitHub resolve the tip at query time, so the session's own just-pushed commits count.
    A 404/422 is a definitive no (hallucinated SHA, or the branch vanished); other errors propagate
    so the caller's retry machinery re-checks later.
    """
    try:
        response = github_api_request(
            "GET",
            f"/repos/{owner}/{repo}/compare/{branch}...{sha}",
            token=token,
            endpoint="/repos/{owner}/{repo}/compare/{basehead}",
            installation_id=installation_id,
            # The compare payload carries commit lists + file diffs we don't need; keep it minimal.
            params={"per_page": 1},
        )
    except GitHubAPIError as e:
        if e.status in (404, 422):
            return False
        raise
    return response.json().get("status") in ("behind", "identical")


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
    A FIXED verdict whose commit failed server-side verification never resolves either: the model's
    claim is unproven, so the thread stays open for a human. None (unchecked) keeps legacy behavior.
    The same holds for a commit touching restricted paths (`commit_restricted`) — the hard-floor
    backstop leaves it for a human.
    """
    if verdict.outcome == "fixed" and (verdict.commit_verified is False or verdict.commit_restricted):
        return False
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
