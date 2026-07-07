"""Orchestration for engineering_analytics.

Resolves caller inputs (PostHog-convention date strings, ``owner/name`` repo) and binds the
team to its curated GitHub read layer (``CuratedGitHubSource``, which resolves the warehouse
table names), then returns canonical contract types. The curated query builders
(``backend/logic/views``) own all GitHub-shaped mapping and domain rules; this layer deals
only in canonical types.
"""

from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING

from posthog.models.team import Team
from posthog.utils import relative_date_parse

from products.engineering_analytics.backend.facade.contracts import (
    CICardSummary,
    CIFailureLogs,
    CommitPRMatch,
    GitHubSource,
    MasterFailureGroup,
    PRCostSummary,
    PRLifecycle,
    PullRequestList,
    RepoOverview,
    RunFailureLogs,
    WorkflowCost,
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
from products.engineering_analytics.backend.logic.queries.llm_spend import query_pr_llm_spend
from products.engineering_analytics.backend.logic.queries.master_failures import query_master_failures
from products.engineering_analytics.backend.logic.queries.pr_cost import (
    query_author_workflow_costs,
    query_pr_cost,
    query_workflow_runner_costs,
)
from products.engineering_analytics.backend.logic.queries.pr_lifecycle import query_pr_lifecycle
from products.engineering_analytics.backend.logic.queries.pr_runs import query_pr_runs
from products.engineering_analytics.backend.logic.queries.pull_request_list import query_pull_request_list
from products.engineering_analytics.backend.logic.queries.repo_overview import query_default_branch, query_repo_overview
from products.engineering_analytics.backend.logic.queries.repo_run_activity import query_repo_run_activity
from products.engineering_analytics.backend.logic.queries.resolve_commit import query_resolve_commit
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


def build_resolve_commit(
    *, curated: CuratedGitHubSource, sha: str | None, branch: str | None, repo: str | None
) -> list[CommitPRMatch]:
    resolved_sha = (sha or "").strip()
    resolved_branch = (branch or "").strip()
    if not resolved_sha and not resolved_branch:
        raise ValueError("provide a commit sha or a branch to resolve")
    # A too-short prefix would over-match unrelated commits; reject it rather than resolve to noise.
    if resolved_sha and len(resolved_sha) < 7:
        raise ValueError("sha must be at least 7 characters")
    # repo is an optional narrowing filter: absent -> (None, None); malformed (bare org) -> raises.
    owner, name = _split_repo(repo)
    return query_resolve_commit(
        curated=curated,
        sha=resolved_sha or None,
        branch=resolved_branch or None,
        repo_owner=owner,
        repo_name=name,
    )


def build_ci_failure_logs(*, curated: CuratedGitHubSource, pr_number: int, repo: str | None) -> CIFailureLogs:
    owner, name = _split_repo(repo)
    if not (owner and name):
        raise ValueError("repo must be in 'owner/name' format")
    return query_ci_failure_logs(curated=curated, pr_number=pr_number, repo_owner=owner, repo_name=name)


def build_pr_cost(*, curated: CuratedGitHubSource, pr_number: int, repo: str | None) -> PRCostSummary:
    owner, name = _split_repo(repo)
    if not (owner and name):
        raise ValueError("repo must be in 'owner/name' format")
    # LLM token spend is an additive component joined by branch from the events table; it is independent
    # of the CI job cost (which reads the warehouse), so both are computed and merged here rather than
    # threaded through the CI-cost query.
    summary = query_pr_cost(curated=curated, pr_number=pr_number, repo_owner=owner, repo_name=name)
    llm_spend = query_pr_llm_spend(curated=curated, pr_number=pr_number, repo_owner=owner, repo_name=name)
    return replace(summary, llm_spend=llm_spend)


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
    owner, name = _split_repo(repo)
    if not (owner and name):
        raise ValueError("repo must be in 'owner/name' format")
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
    owner, name = _split_repo(repo)
    if not (owner and name):
        raise ValueError("repo must be in 'owner/name' format")
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


def build_author_workflow_costs(
    *,
    curated: CuratedGitHubSource,
    author: str,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[WorkflowCost]:
    if not author.strip():
        raise ValueError("author is required")
    parsed_from, parsed_to = _parse_window(curated.team, date_from, date_to, default=_DEFAULT_WINDOW)
    return query_author_workflow_costs(curated=curated, author=author.strip(), date_from=parsed_from, date_to=parsed_to)


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
    parsed_from, parsed_to = _parse_window(curated.team, date_from, date_to, default=_DEFAULT_WORKFLOW_WINDOW)
    return query_workflow_health(curated=curated, date_from=parsed_from, date_to=parsed_to, branch=branch)


def _parse_date(team: Team, value: str) -> datetime:
    return relative_date_parse(value, team.timezone_info)


def _parse_window(
    team: Team, date_from: str | None, date_to: str | None, *, default: str
) -> tuple[datetime, datetime | None]:
    """Resolve a caller's date window against the team timezone, capping the span at _MAX_WINDOW_DAYS."""
    parsed_from = _parse_date(team, date_from or default)
    parsed_to = _parse_date(team, date_to) if date_to else None
    span_days = ((parsed_to or datetime.now(tz=parsed_from.tzinfo)) - parsed_from).days
    if span_days > _MAX_WINDOW_DAYS:
        raise ValueError(f"date window spans {span_days} days; the maximum is {_MAX_WINDOW_DAYS}")
    return parsed_from, parsed_to


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
    parsed_from, parsed_to = _parse_window(curated.team, date_from, date_to, default=_DEFAULT_WINDOW)
    return query_repo_overview(curated=curated, date_from=parsed_from, date_to=parsed_to)


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
