"""HogQL assembly of a single PR's lifecycle over the curated query builders.

Embeds the curated ``github_pull_requests`` / ``github_workflow_runs`` builders
as subqueries (via ``_curated``) — the product runs this privately rather than
registering a global view. The curated SELECTs already carry the derived columns
(canonical ``state``, ``is_bot``, repo identity, ``head_sha``), so this layer only
shapes the rows into the ``PRLifecycle`` contract; no GitHub-isms or domain rules
live here.
"""

from datetime import datetime

from posthog.hogql import ast

from products.engineering_analytics.backend.facade.contracts import (
    Author,
    PRLifecycle,
    PRLifecycleEvent,
    PRLifecycleEventKind,
    PRState,
    PullRequest,
    RepoRef,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries._pr_header import pr_header_placeholders, pr_header_query

# The curated subqueries and the repo filter are filled with str.replace (trusted
# constants), leaving the HogQL {value} placeholders untouched for parse_select.
_HEADER = pr_header_query(
    """
        id, number, title, state, is_draft,
        created_at, merged_at, closed_at,
        author_handle, author_avatar_url, is_bot,
        repo_owner, repo_name, head_sha
    """
)

_RUNS = """
    SELECT id, workflow_name, status, conclusion, run_started_at, updated_at
    FROM __RUNS_SOURCE__ AS r
    WHERE head_sha = {head_sha}
    ORDER BY run_started_at ASC
"""


def query_pr_lifecycle(
    *,
    curated: CuratedGitHubSource,
    pr_number: int,
    repo_owner: str,
    repo_name: str,
) -> PRLifecycle | None:
    placeholders = pr_header_placeholders(pr_number=pr_number, repo_owner=repo_owner, repo_name=repo_name)
    header_sql = _HEADER.replace("__PR_SOURCE__", curated.pr_source())
    header = curated.run(
        header_sql,
        query_type="engineering_analytics.pr_lifecycle.header",
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

    events: list[PRLifecycleEvent] = []

    def add(
        kind: PRLifecycleEventKind, at: datetime | None, *, detail: str | None = None, run_id: int | None = None
    ) -> None:
        # Timestamps come from parseDateTimeBestEffort, which yields NULL on a malformed/missing
        # value, so `at` can be None. Skip those events — a timeline can't place an event with no
        # time, and `at` is non-nullable on the contract, so building one would raise. Guarding
        # here keeps a single bad run timestamp from failing the whole PR's lifecycle (and the
        # sort below never sees a None key).
        if at is not None:
            events.append(PRLifecycleEvent(kind=kind, at=at, detail=detail, run_id=run_id))

    add(PRLifecycleEventKind.OPENED, created_at)
    runs = (
        curated.run(
            _RUNS.replace("__RUNS_SOURCE__", curated.run_source()),
            query_type="engineering_analytics.pr_lifecycle.runs",
            placeholders={"head_sha": ast.Constant(value=head_sha)},
        )
        if head_sha
        else None
    )
    if runs is not None:
        for run_id, workflow_name, status, conclusion, run_started_at, updated_at in runs.results:
            run_id = int(run_id) if run_id is not None else None
            add(PRLifecycleEventKind.CI_STARTED, run_started_at, detail=workflow_name, run_id=run_id)
            if status == "completed":
                detail = f"{workflow_name}: {conclusion}" if conclusion else workflow_name
                add(PRLifecycleEventKind.CI_FINISHED, updated_at, detail=detail, run_id=run_id)

    if merged_at is not None:
        add(PRLifecycleEventKind.MERGED, merged_at)
    elif closed_at is not None:
        add(PRLifecycleEventKind.CLOSED, closed_at)

    events.sort(key=lambda event: event.at)
    return PRLifecycle(pull_request=pull_request, events=events)
