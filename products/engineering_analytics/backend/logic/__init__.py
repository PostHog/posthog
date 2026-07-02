"""Orchestration for engineering_analytics.

Resolves caller inputs (PostHog-convention date strings, ``owner/name`` repo) and binds the
team to its curated GitHub read layer (``CuratedGitHubSource``, which resolves the warehouse
table names), then returns canonical contract types. The curated query builders
(``backend/logic/views``) own all GitHub-shaped mapping and domain rules; this layer deals
only in canonical types.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from posthog.models.team import Team
from posthog.utils import relative_date_parse

from products.engineering_analytics.backend.facade.contracts import (
    CICardSummary,
    CIFailureLogs,
    GitHubSource,
    MasterFailureGroup,
    PRCostSummary,
    PRLifecycle,
    PullRequestList,
    RepoOverview,
    RunFailureLogs,
    WorkflowHealthItem,
    WorkflowJob,
    WorkflowJobAggregate,
    WorkflowRunActivity,
    WorkflowRunDetail,
    WorkflowRunnerCost,
)
from products.engineering_analytics.backend.logic.quarantine import (
    build_quarantine as build_quarantine,
    request_quarantine as request_quarantine,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.ci_cards import query_ci_cards
from products.engineering_analytics.backend.logic.queries.ci_failure_logs import (
    query_ci_failure_logs,
    query_run_failure_logs,
)
from products.engineering_analytics.backend.logic.queries.job_aggregates import query_job_aggregates
from products.engineering_analytics.backend.logic.queries.master_failures import query_master_failures
from products.engineering_analytics.backend.logic.queries.pr_cost import query_pr_cost, query_workflow_runner_costs
from products.engineering_analytics.backend.logic.queries.pr_lifecycle import query_pr_lifecycle
from products.engineering_analytics.backend.logic.queries.pr_runs import query_pr_runs
from products.engineering_analytics.backend.logic.queries.pull_request_list import query_pull_request_list
from products.engineering_analytics.backend.logic.queries.repo_overview import query_default_branch, query_repo_overview
from products.engineering_analytics.backend.logic.queries.workflow_health import query_workflow_health
from products.engineering_analytics.backend.logic.queries.workflow_jobs import query_workflow_jobs
from products.engineering_analytics.backend.logic.queries.workflow_run import query_workflow_run
from products.engineering_analytics.backend.logic.queries.workflow_run_activity import query_workflow_run_activity
from products.engineering_analytics.backend.logic.queries.workflow_run_list import query_workflow_run_list
from products.engineering_analytics.backend.logic.sources import list_github_sources

if TYPE_CHECKING:
    from posthog.rbac.user_access_control import UserAccessControl

# Default recency window when a caller omits date_from. Relative strings (-30d) and
# ISO8601 are both accepted and resolved against the team's timezone.
_DEFAULT_WINDOW = "-30d"

# Workflow health defaults to a tighter window than the PR backlog — CI health is a "right now"
# question, and the short window also buckets by hour for a live-looking trend.
_DEFAULT_WORKFLOW_WINDOW = "-24h"

# workflow_health zero-fills one daily entry per workflow per day in the window, so an
# unbounded range would materialize an enormous response. A year is plenty for trends.
_MAX_WINDOW_DAYS = 366


# Each builder operates on an already-resolved CuratedGitHubSource: source selection and per-source
# warehouse access control happen once at the facade, which hands these builders the authorized
# handle. They validate their own inputs (dates, repo) and read PR/CI data through the handle.
def build_pr_lifecycle(*, curated: CuratedGitHubSource, pr_number: int, repo: str | None) -> PRLifecycle | None:
    owner, name = _split_repo(repo)
    if not (owner and name):
        raise ValueError("repo must be in 'owner/name' format")
    return query_pr_lifecycle(curated=curated, pr_number=pr_number, repo_owner=owner, repo_name=name)


def build_pr_runs(*, curated: CuratedGitHubSource, pr_number: int, repo: str | None) -> list[WorkflowRunDetail]:
    owner, name = _split_repo(repo)
    if not (owner and name):
        raise ValueError("repo must be in 'owner/name' format")
    return query_pr_runs(curated=curated, pr_number=pr_number, repo_owner=owner, repo_name=name)


def build_ci_failure_logs(*, curated: CuratedGitHubSource, pr_number: int, repo: str | None) -> CIFailureLogs:
    owner, name = _split_repo(repo)
    if not (owner and name):
        raise ValueError("repo must be in 'owner/name' format")
    return query_ci_failure_logs(curated=curated, pr_number=pr_number, repo_owner=owner, repo_name=name)


def build_pr_cost(*, curated: CuratedGitHubSource, pr_number: int, repo: str | None) -> PRCostSummary:
    owner, name = _split_repo(repo)
    if not (owner and name):
        raise ValueError("repo must be in 'owner/name' format")
    return query_pr_cost(curated=curated, pr_number=pr_number, repo_owner=owner, repo_name=name)


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
    owner, name = _split_repo(repo)
    if not (owner and name):
        raise ValueError("repo must be in 'owner/name' format")
    parsed_from = _parse_date(curated.team, date_from or _DEFAULT_WINDOW)
    parsed_to = _parse_date(curated.team, date_to) if date_to else None
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
    owner, name = _split_repo(repo)
    if not (owner and name):
        raise ValueError("repo must be in 'owner/name' format")
    parsed_from = _parse_date(curated.team, date_from or _DEFAULT_WINDOW)
    parsed_to = _parse_date(curated.team, date_to) if date_to else None
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
    owner, name = _split_repo(repo)
    if not (owner and name):
        raise ValueError("repo must be in 'owner/name' format")
    parsed_from = _parse_date(curated.team, date_from or _DEFAULT_WINDOW)
    parsed_to = _parse_date(curated.team, date_to) if date_to else None
    return query_workflow_runner_costs(
        curated=curated,
        repo_owner=owner,
        repo_name=name,
        workflow_name=workflow_name,
        date_from=parsed_from,
        date_to=parsed_to,
        branch=branch,
    )


def build_ci_cards(*, curated: CuratedGitHubSource) -> CICardSummary:
    return query_ci_cards(curated=curated)


# Listing the team's connected sources is its own concern (no curated read handle): it threads the
# requesting user's access control so the picker can't enumerate sources the user can't access.
def build_github_sources(*, team: Team, user_access_control: "UserAccessControl | None" = None) -> list[GitHubSource]:
    return list_github_sources(team=team, user_access_control=user_access_control)


def build_pull_request_list(
    *, curated: CuratedGitHubSource, date_from: str | None = None, author: str | None = None
) -> PullRequestList:
    parsed_from = _parse_date(curated.team, date_from or _DEFAULT_WINDOW)
    return query_pull_request_list(curated=curated, date_from=parsed_from, author=author)


def build_workflow_health(
    *,
    curated: CuratedGitHubSource,
    date_from: str | None = None,
    date_to: str | None = None,
    branch: str | None = None,
) -> list[WorkflowHealthItem]:
    parsed_from = _parse_date(curated.team, date_from or _DEFAULT_WORKFLOW_WINDOW)
    parsed_to = _parse_date(curated.team, date_to) if date_to else None
    span_days = ((parsed_to or datetime.now(tz=parsed_from.tzinfo)) - parsed_from).days
    if span_days > _MAX_WINDOW_DAYS:
        raise ValueError(f"date window spans {span_days} days; the maximum is {_MAX_WINDOW_DAYS}")
    return query_workflow_health(curated=curated, date_from=parsed_from, date_to=parsed_to, branch=branch)


def _parse_date(team: Team, value: str) -> datetime:
    return relative_date_parse(value, team.timezone_info)


def _split_repo(repo: str | None) -> tuple[str | None, str | None]:
    if not repo:
        return None, None
    owner, _, name = repo.partition("/")
    # A half-specified repo (bare org, trailing/leading slash) would otherwise drop
    # the filter silently and return a PR from the wrong repo — fail loudly instead.
    if not (owner and name):
        raise ValueError(f"repo must be in 'owner/name' format, got: {repo!r}")
    return owner, name


def build_repo_overview(
    *,
    curated: CuratedGitHubSource,
    date_from: str | None = None,
    date_to: str | None = None,
) -> RepoOverview:
    parsed_from = _parse_date(curated.team, date_from or _DEFAULT_WINDOW)
    parsed_to = _parse_date(curated.team, date_to) if date_to else None
    span_days = ((parsed_to or datetime.now(tz=parsed_from.tzinfo)) - parsed_from).days
    if span_days > _MAX_WINDOW_DAYS:
        raise ValueError(f"date window spans {span_days} days; the maximum is {_MAX_WINDOW_DAYS}")
    return query_repo_overview(curated=curated, date_from=parsed_from, date_to=parsed_to)


def build_master_failures(
    *,
    curated: CuratedGitHubSource,
    date_from: str | None = None,
    date_to: str | None = None,
    branch: str | None = None,
) -> list[MasterFailureGroup]:
    parsed_from = _parse_date(curated.team, date_from or _DEFAULT_WORKFLOW_WINDOW)
    parsed_to = _parse_date(curated.team, date_to) if date_to else None
    span_days = ((parsed_to or datetime.now(tz=parsed_from.tzinfo)) - parsed_from).days
    if span_days > _MAX_WINDOW_DAYS:
        raise ValueError(f"date window spans {span_days} days; the maximum is {_MAX_WINDOW_DAYS}")
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
    parsed_from = _parse_date(curated.team, date_from or _DEFAULT_WINDOW)
    parsed_to = _parse_date(curated.team, date_to) if date_to else None
    span_days = ((parsed_to or datetime.now(tz=parsed_from.tzinfo)) - parsed_from).days
    if span_days > _MAX_WINDOW_DAYS:
        raise ValueError(f"date window spans {span_days} days; the maximum is {_MAX_WINDOW_DAYS}")
    return query_job_aggregates(
        curated=curated, workflow_name=workflow_name, date_from=parsed_from, date_to=parsed_to, branch=branch
    )
