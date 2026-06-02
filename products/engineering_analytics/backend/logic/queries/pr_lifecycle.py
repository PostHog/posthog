"""HogQL assembly of a single PR's lifecycle over the curated read layer.

Reads the ``engineering_analytics_pull_requests`` and
``engineering_analytics_workflow_runs`` views — never the raw ``github_*``
tables. The views already carry the derived columns (canonical ``state``,
``is_bot``, repo identity, ``head_sha``), so this layer only shapes the rows into
the ``PRLifecycle`` contract; no GitHub-isms or domain rules live here.
"""

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models.team import Team

from products.engineering_analytics.backend.facade.contracts import (
    Author,
    PRLifecycle,
    PRLifecycleEvent,
    PRLifecycleEventKind,
    PRState,
    PullRequest,
    RepoRef,
)
from products.engineering_analytics.backend.logic.views import pull_requests, workflow_runs

# View names and the repo filter are filled with str.replace (trusted constants),
# leaving the HogQL {value} placeholders untouched for parse_select.
_HEADER = """
    SELECT
        id, number, title, state, is_draft,
        created_at, merged_at, closed_at,
        author_handle, author_avatar_url, is_bot,
        repo_owner, repo_name, head_sha
    FROM __PR_VIEW__
    WHERE number = {pr_number} __REPO_FILTER__
    ORDER BY created_at DESC
    LIMIT 1
"""

_RUNS = """
    SELECT workflow_name, status, conclusion, run_started_at, updated_at
    FROM __RUNS_VIEW__
    WHERE head_sha = {head_sha}
    ORDER BY run_started_at ASC
"""


def query_pr_lifecycle(
    *,
    team: Team,
    pr_number: int,
    repo_owner: str | None,
    repo_name: str | None,
) -> PRLifecycle | None:
    placeholders: dict[str, ast.Expr] = {"pr_number": ast.Constant(value=pr_number)}
    repo_filter = ""
    if repo_owner and repo_name:
        repo_filter = "AND repo_owner = {repo_owner} AND repo_name = {repo_name}"
        placeholders["repo_owner"] = ast.Constant(value=repo_owner)
        placeholders["repo_name"] = ast.Constant(value=repo_name)

    header_sql = _HEADER.replace("__PR_VIEW__", pull_requests.VIEW_NAME).replace("__REPO_FILTER__", repo_filter)
    header = execute_hogql_query(
        query=parse_select(header_sql, placeholders=placeholders),
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
        is_bot,
        owner,
        name,
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
            is_bot=bool(is_bot),
        ),
        repo=RepoRef(provider="github", owner=owner, name=name),
        state=PRState(state),
        is_draft=bool(is_draft),
        created_at=created_at,
        merged_at=merged_at,
        closed_at=closed_at,
    )

    events = [PRLifecycleEvent(kind=PRLifecycleEventKind.OPENED, at=created_at)]
    if head_sha:
        runs = execute_hogql_query(
            query=parse_select(
                _RUNS.replace("__RUNS_VIEW__", workflow_runs.VIEW_NAME),
                placeholders={"head_sha": ast.Constant(value=head_sha)},
            ),
            team=team,
            query_type="engineering_analytics.pr_lifecycle.runs",
        )
        for workflow_name, status, conclusion, run_started_at, updated_at in runs.results:
            events.append(
                PRLifecycleEvent(kind=PRLifecycleEventKind.CI_STARTED, at=run_started_at, detail=workflow_name)
            )
            if status == "completed":
                detail = f"{workflow_name}: {conclusion}" if conclusion else workflow_name
                events.append(PRLifecycleEvent(kind=PRLifecycleEventKind.CI_FINISHED, at=updated_at, detail=detail))

    if merged_at is not None:
        events.append(PRLifecycleEvent(kind=PRLifecycleEventKind.MERGED, at=merged_at))
    elif closed_at is not None:
        events.append(PRLifecycleEvent(kind=PRLifecycleEventKind.CLOSED, at=closed_at))

    events.sort(key=lambda event: event.at)
    return PRLifecycle(pull_request=pull_request, events=events)
