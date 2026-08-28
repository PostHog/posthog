"""Workflow/run/job-scoped orchestration: health, activity, jobs, costs, and repo-level state."""

from products.engineering_analytics.backend.facade.contracts import (
    CurrentBranchHealth,
    MasterFailureGroup,
    RepoOverview,
    RunFailureLogs,
    WorkflowHealthItem,
    WorkflowHealthRunScope,
    WorkflowJob,
    WorkflowJobAggregate,
    WorkflowRunActivity,
    WorkflowRunDetail,
    WorkflowRunnerCost,
)
from products.engineering_analytics.backend.logic._shared import _DEFAULT_WINDOW, _parse_window, _require_repo
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.ci_failure_logs import query_run_failure_logs
from products.engineering_analytics.backend.logic.queries.current_branch_health import query_current_branch_health
from products.engineering_analytics.backend.logic.queries.job_aggregates import query_job_aggregates
from products.engineering_analytics.backend.logic.queries.master_failures import query_master_failures
from products.engineering_analytics.backend.logic.queries.pr_cost import query_workflow_runner_costs
from products.engineering_analytics.backend.logic.queries.repo_overview import (
    empty_repo_series,
    query_default_branch,
    query_repo_overview,
    query_repo_series,
)
from products.engineering_analytics.backend.logic.queries.repo_run_activity import query_repo_run_activity
from products.engineering_analytics.backend.logic.queries.workflow_health import query_workflow_health
from products.engineering_analytics.backend.logic.queries.workflow_jobs import query_workflow_jobs
from products.engineering_analytics.backend.logic.queries.workflow_run import query_workflow_run
from products.engineering_analytics.backend.logic.queries.workflow_run_activity import query_workflow_run_activity
from products.engineering_analytics.backend.logic.queries.workflow_run_list import query_workflow_run_list

# Workflow health defaults to a tighter window than the PR backlog — CI health is a "right now"
# question, and the short window also buckets by hour for a live-looking trend.
_DEFAULT_WORKFLOW_WINDOW = "-24h"


def build_workflow_run(*, curated: CuratedGitHubSource, run_id: int) -> WorkflowRunDetail | None:
    return query_workflow_run(curated=curated, run_id=run_id)


def build_workflow_jobs(
    *, curated: CuratedGitHubSource, run_id: int, run_attempt: int | None = None
) -> list[WorkflowJob]:
    return query_workflow_jobs(curated=curated, run_id=run_id, run_attempt=run_attempt)


def build_workflow_run_list(
    *,
    curated: CuratedGitHubSource,
    repo: str | None,
    workflow_name: str,
    date_from: str | None = None,
    date_to: str | None = None,
    branch: str | None = None,
) -> list[WorkflowRunDetail]:
    owner, name = _require_repo(repo)
    parsed_from, parsed_to = _parse_window(curated.team, date_from, date_to, default=_DEFAULT_WINDOW)
    return query_workflow_run_list(
        curated=curated,
        repo_owner=owner,
        repo_name=name,
        workflow_name=workflow_name,
        date_from=parsed_from,
        date_to=parsed_to,
        branch=branch,
    )


def build_workflow_run_activity(
    *,
    curated: CuratedGitHubSource,
    repo: str | None,
    workflow_name: str,
    date_from: str | None = None,
    date_to: str | None = None,
    branch: str | None = None,
) -> WorkflowRunActivity:
    owner, name = _require_repo(repo)
    parsed_from, parsed_to = _parse_window(curated.team, date_from, date_to, default=_DEFAULT_WINDOW)
    return query_workflow_run_activity(
        curated=curated,
        repo_owner=owner,
        repo_name=name,
        workflow_name=workflow_name,
        date_from=parsed_from,
        date_to=parsed_to,
        branch=branch,
    )


def build_workflow_runner_costs(
    *,
    curated: CuratedGitHubSource,
    repo: str | None,
    workflow_name: str,
    date_from: str | None = None,
    date_to: str | None = None,
    branch: str | None = None,
) -> list[WorkflowRunnerCost]:
    owner, name = _require_repo(repo)
    parsed_from, parsed_to = _parse_window(curated.team, date_from, date_to, default=_DEFAULT_WINDOW)
    return query_workflow_runner_costs(
        curated=curated,
        repo_owner=owner,
        repo_name=name,
        workflow_name=workflow_name,
        date_from=parsed_from,
        date_to=parsed_to,
        branch=branch,
    )


def build_workflow_health(
    *,
    curated: CuratedGitHubSource,
    date_from: str | None = None,
    date_to: str | None = None,
    branch: str | None = None,
    run_scope: str | None = None,
) -> list[WorkflowHealthItem]:
    parsed_from, parsed_to = _parse_window(curated.team, date_from, date_to, default=_DEFAULT_WORKFLOW_WINDOW)
    return query_workflow_health(
        curated=curated,
        date_from=parsed_from,
        date_to=parsed_to,
        branch=branch,
        run_scope=_parse_run_scope(run_scope),
    )


def _parse_run_scope(value: str | None) -> WorkflowHealthRunScope:
    """Absent/blank selects 'all'; anything else must be an exact enum value (ValueError → 400)."""
    normalized = value.strip() if value else ""
    if not normalized:
        return WorkflowHealthRunScope.ALL
    try:
        return WorkflowHealthRunScope(normalized)
    except ValueError:
        raise ValueError(
            f"run_scope must be one of: {', '.join(scope.value for scope in WorkflowHealthRunScope)}"
        ) from None


def build_repo_overview(
    *,
    curated: CuratedGitHubSource,
    date_from: str | None = None,
    date_to: str | None = None,
    include_series: bool = True,
) -> RepoOverview:
    parsed_from, parsed_to = _parse_window(curated.team, date_from, date_to, default=_DEFAULT_WINDOW)
    # The one place the endpoint's include_series toggle decides anything: headline-only consumers
    # (the weekly digest) compose the empty series instead of paying the four chart scans.
    series = (
        query_repo_series(curated=curated, date_from=parsed_from, date_to=parsed_to)
        if include_series
        else empty_repo_series(date_from=parsed_from, date_to=parsed_to)
    )
    return query_repo_overview(curated=curated, date_from=parsed_from, date_to=parsed_to, series=series)


def build_current_branch_health(*, curated: CuratedGitHubSource) -> CurrentBranchHealth:
    date_from, date_to = _parse_window(curated.team, None, None, default=_DEFAULT_WORKFLOW_WINDOW)
    branch = query_default_branch(curated=curated, date_from=date_from, date_to=date_to)
    return query_current_branch_health(curated=curated, date_from=date_from, branch=branch)


def build_repo_run_activity(
    *,
    curated: CuratedGitHubSource,
    date_from: str | None = None,
    date_to: str | None = None,
    branch: str | None = None,
) -> WorkflowRunActivity:
    parsed_from, parsed_to = _parse_window(curated.team, date_from, date_to, default=_DEFAULT_WINDOW)
    resolved_branch = (branch or "").strip()
    if not resolved_branch:
        # No branch given: collapse the repo's default branch, as observed in the window.
        resolved_branch = query_default_branch(curated=curated, date_from=parsed_from, date_to=parsed_to)
    return query_repo_run_activity(curated=curated, date_from=parsed_from, date_to=parsed_to, branch=resolved_branch)


def build_master_failures(
    *,
    curated: CuratedGitHubSource,
    date_from: str | None = None,
    date_to: str | None = None,
    branch: str | None = None,
) -> list[MasterFailureGroup]:
    parsed_from, parsed_to = _parse_window(curated.team, date_from, date_to, default=_DEFAULT_WORKFLOW_WINDOW)
    resolved_branch = (branch or "").strip()
    if not resolved_branch:
        # No branch given: use the repo's default branch as observed in the window.
        resolved_branch = query_default_branch(curated=curated, date_from=parsed_from, date_to=parsed_to)
    return query_master_failures(curated=curated, date_from=parsed_from, date_to=parsed_to, branch=resolved_branch)


def build_run_failure_logs(*, curated: CuratedGitHubSource, run_id: int) -> RunFailureLogs:
    return query_run_failure_logs(curated=curated, run_id=run_id)


def build_job_aggregates(
    *,
    curated: CuratedGitHubSource,
    workflow_name: str,
    date_from: str | None = None,
    date_to: str | None = None,
    branch: str | None = None,
) -> list[WorkflowJobAggregate]:
    parsed_from, parsed_to = _parse_window(curated.team, date_from, date_to, default=_DEFAULT_WINDOW)
    return query_job_aggregates(
        curated=curated, workflow_name=workflow_name, date_from=parsed_from, date_to=parsed_to, branch=branch
    )
