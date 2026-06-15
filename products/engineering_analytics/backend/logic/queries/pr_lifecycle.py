"""HogQL assembly of a single PR's lifecycle over the curated query builders.

Embeds the curated ``github_pull_requests`` / ``github_workflow_runs`` builders
as subqueries (via ``_curated``) — the product runs this privately rather than
registering a global view. The curated SELECTs already carry the derived columns
(canonical ``state``, ``is_bot``, repo identity, ``head_sha``), so this layer only
shapes the rows into the ``PRLifecycle`` contract; no GitHub-isms or domain rules
live here.
"""

from posthog.hogql import ast

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
from products.engineering_analytics.backend.logic.queries import _curated
from products.engineering_analytics.backend.logic.sources import GitHubTables

# The curated subqueries and the repo filter are filled with str.replace (trusted
# constants), leaving the HogQL {value} placeholders untouched for parse_select.
_HEADER = """
    SELECT
        id, number, title, state, is_draft,
        created_at, merged_at, closed_at,
        author_handle, author_avatar_url, is_bot,
        repo_owner, repo_name, head_sha
    FROM __PR_SOURCE__ AS pr
    WHERE number = {pr_number} __REPO_FILTER__
    ORDER BY created_at DESC
    LIMIT 1
"""

_RUNS = """
    SELECT id, workflow_name, status, conclusion, run_started_at, updated_at
    FROM __RUNS_SOURCE__ AS r
    WHERE head_sha = {head_sha}
    ORDER BY run_started_at ASC
"""


def query_pr_lifecycle(
    *,
    team: Team,
    tables: GitHubTables,
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

    header_sql = _HEADER.replace("__PR_SOURCE__", _curated.pr_source(tables.pull_requests)).replace(
        "__REPO_FILTER__", repo_filter
    )
    header = _curated.run_query(
        header_sql,
        team=team,
        query_type="engineering_analytics.pr_lifecycle.header",
        tables=tables,
        placeholders=placeholders,
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
    runs = (
        _curated.run_query(
            _RUNS.replace("__RUNS_SOURCE__", _curated.run_source(tables.workflow_runs)),
            team=team,
            query_type="engineering_analytics.pr_lifecycle.runs",
            tables=tables,
            placeholders={"head_sha": ast.Constant(value=head_sha)},
        )
        if head_sha
        else None
    )
    if runs is not None:
        for run_id, workflow_name, status, conclusion, run_started_at, updated_at in runs.results:
            run_id = int(run_id) if run_id is not None else None
            events.append(
                PRLifecycleEvent(
                    kind=PRLifecycleEventKind.CI_STARTED, at=run_started_at, detail=workflow_name, run_id=run_id
                )
            )
            if status == "completed":
                detail = f"{workflow_name}: {conclusion}" if conclusion else workflow_name
                events.append(
                    PRLifecycleEvent(kind=PRLifecycleEventKind.CI_FINISHED, at=updated_at, detail=detail, run_id=run_id)
                )

    if merged_at is not None:
        events.append(PRLifecycleEvent(kind=PRLifecycleEventKind.MERGED, at=merged_at))
    elif closed_at is not None:
        events.append(PRLifecycleEvent(kind=PRLifecycleEventKind.CLOSED, at=closed_at))

    events.sort(key=lambda event: event.at)
    return PRLifecycle(pull_request=pull_request, events=events)
