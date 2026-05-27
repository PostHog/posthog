"""HogQL against ``github_pull_requests`` for time_to_merge and pr_lifecycle.

Nested GitHub objects (``user``, ``head``) are stored as JSON strings on the
warehouse table, so author handle and head SHA are read with
``JSONExtractString``. Bot detection lives here (the query / mapping layer) per
SPEC.md section 7: a handle is a bot if it ends in ``[bot]`` (every GitHub App
gets that suffix) or is in the small hardcoded allowlist below.
"""

from datetime import datetime

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models.team import Team

from ...facade.contracts import (
    Author,
    BucketKind,
    PRLifecycle,
    PRLifecycleEvent,
    PRLifecycleEventKind,
    PRState,
    PullRequest,
    RepoRef,
    TimeToMergeRow,
)

# Bots whose handle does not carry GitHub's automatic ``[bot]`` suffix. Kept
# deliberately small; per-team configuration is deferred (SPEC.md section 7).
KNOWN_BOT_HANDLES: frozenset[str] = frozenset(
    {
        "posthog-bot",
        "dependabot",
        "renovate",
        "github-actions",
    }
)

_HANDLE = "JSONExtractString(user, 'login')"

# Shared row filter: merged in the window, not a draft, not a bot. Plain string
# concatenation (not an f-string) keeps the {placeholders} intact for parse_select.
_TIME_TO_MERGE_WHERE = (
    " merged_at IS NOT NULL"
    " AND merged_at >= {date_from} AND merged_at < {date_to}"
    " AND NOT coalesce(draft, false)"
    " AND NOT (" + _HANDLE + " LIKE '%[bot]' OR " + _HANDLE + " IN {bot_handles})"
)

_TIME_TO_MERGE_AGG = (
    " count() AS pr_count,"
    " quantile(0.5)(dateDiff('second', created_at, merged_at)) AS median_seconds,"
    " quantile(0.95)(dateDiff('second', created_at, merged_at)) AS p95_seconds"
)

_TIME_TO_MERGE_ALL = (
    "SELECT 'all' AS bucket," + _TIME_TO_MERGE_AGG + " FROM github_pull_requests WHERE" + _TIME_TO_MERGE_WHERE
)

_TIME_TO_MERGE_BY_AUTHOR = (
    "SELECT "
    + _HANDLE
    + " AS bucket,"
    + _TIME_TO_MERGE_AGG
    + " FROM github_pull_requests WHERE"
    + _TIME_TO_MERGE_WHERE
    + " GROUP BY bucket ORDER BY pr_count DESC"
)


def is_bot_handle(handle: str) -> bool:
    return handle.endswith("[bot]") or handle in KNOWN_BOT_HANDLES


def query_time_to_merge(
    *,
    team: Team,
    date_from: datetime,
    date_to: datetime,
    group_by_author: bool,
) -> list[TimeToMergeRow]:
    placeholders = {
        "date_from": ast.Constant(value=date_from),
        "date_to": ast.Constant(value=date_to),
        "bot_handles": ast.Constant(value=sorted(KNOWN_BOT_HANDLES)),
    }
    query = parse_select(
        _TIME_TO_MERGE_BY_AUTHOR if group_by_author else _TIME_TO_MERGE_ALL,
        placeholders=placeholders,
    )
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type="engineering_analytics.time_to_merge",
    )
    bucket_kind = BucketKind.AUTHOR if group_by_author else BucketKind.ALL
    return [
        TimeToMergeRow(
            bucket=bucket,
            bucket_kind=bucket_kind,
            pr_count=pr_count,
            median_seconds=median_seconds,
            p95_seconds=p95_seconds,
        )
        for bucket, pr_count, median_seconds, p95_seconds in response.results
    ]


_PR_HEADER = """
    SELECT
        id, number, title, state,
        coalesce(draft, false) AS is_draft,
        created_at, merged_at, closed_at,
        JSONExtractString(user, 'login') AS author_handle,
        JSONExtractString(user, 'avatar_url') AS author_avatar_url,
        JSONExtractString(head, 'sha') AS head_sha
    FROM github_pull_requests
    WHERE number = {pr_number}
    ORDER BY updated_at DESC
    LIMIT 1
"""

_PR_RUNS = """
    SELECT name, status, conclusion, run_started_at, updated_at
    FROM github_workflow_runs
    WHERE head_sha = {head_sha}
    ORDER BY run_started_at ASC
"""


def query_pr_lifecycle(
    *,
    team: Team,
    pr_number: int,
    repo_ref: RepoRef,
) -> PRLifecycle | None:
    header_query = parse_select(_PR_HEADER, placeholders={"pr_number": ast.Constant(value=pr_number)})
    header = execute_hogql_query(
        query=header_query,
        team=team,
        query_type="engineering_analytics.pr_lifecycle.header",
    )
    if not header.results:
        return None

    (
        pr_id,
        number,
        title,
        state,
        is_draft,
        created_at,
        merged_at,
        closed_at,
        author_handle,
        author_avatar_url,
        head_sha,
    ) = header.results[0]

    pull_request = PullRequest(
        id=pr_id,
        number=number,
        title=title,
        author=Author(
            handle=author_handle,
            display_name=author_handle,
            avatar_url=author_avatar_url,
            is_bot=is_bot_handle(author_handle),
        ),
        repo=repo_ref,
        state=_derive_state(state, merged_at),
        is_draft=bool(is_draft),
        created_at=created_at,
        merged_at=merged_at,
        closed_at=closed_at,
    )

    events = [PRLifecycleEvent(kind=PRLifecycleEventKind.OPENED, at=created_at)]
    if head_sha:
        runs_query = parse_select(_PR_RUNS, placeholders={"head_sha": ast.Constant(value=head_sha)})
        runs = execute_hogql_query(
            query=runs_query,
            team=team,
            query_type="engineering_analytics.pr_lifecycle.runs",
        )
        for name, status, conclusion, run_started_at, updated_at in runs.results:
            events.append(PRLifecycleEvent(kind=PRLifecycleEventKind.CI_STARTED, at=run_started_at, detail=name))
            if status == "completed":
                detail = f"{name}: {conclusion}" if conclusion else name
                events.append(PRLifecycleEvent(kind=PRLifecycleEventKind.CI_FINISHED, at=updated_at, detail=detail))

    if merged_at is not None:
        events.append(PRLifecycleEvent(kind=PRLifecycleEventKind.MERGED, at=merged_at))
    elif closed_at is not None:
        events.append(PRLifecycleEvent(kind=PRLifecycleEventKind.CLOSED, at=closed_at))

    events.sort(key=lambda event: event.at)
    return PRLifecycle(pull_request=pull_request, events=events)


def _derive_state(state: str, merged_at: datetime | None) -> PRState:
    # GitHub's PR list only reports open/closed; merged is closed + a merge timestamp.
    if merged_at is not None:
        return PRState.MERGED
    if state == "closed":
        return PRState.CLOSED
    return PRState.OPEN
