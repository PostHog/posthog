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
    FlakyTestList,
    GitHubSource,
    PRCostSummary,
    PRLifecycle,
    PullRequestList,
    WorkflowHealthItem,
    WorkflowJob,
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
from products.engineering_analytics.backend.logic.queries.ci_failure_logs import query_ci_failure_logs
from products.engineering_analytics.backend.logic.queries.flaky_tests import query_flaky_tests
from products.engineering_analytics.backend.logic.queries.pr_cost import query_pr_cost, query_workflow_runner_costs
from products.engineering_analytics.backend.logic.queries.pr_lifecycle import query_pr_lifecycle
from products.engineering_analytics.backend.logic.queries.pr_runs import query_pr_runs
from products.engineering_analytics.backend.logic.queries.pull_request_list import query_pull_request_list
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

# Flaky-test leaderboard defaults: a week of signal is the triage window, a month the ceiling
# (per-test spans are high-volume and the short Traces retention makes older data spotty anyway).
_DEFAULT_FLAKY_WINDOW = "-7d"
_MAX_FLAKY_WINDOW_DAYS = 30
_DEFAULT_FLAKY_MIN_RERUN_PASSES = 1
_DEFAULT_FLAKY_MIN_FAILED_PRS = 3
_DEFAULT_FLAKY_LIMIT = 50
_MAX_FLAKY_LIMIT = 200


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


def build_flaky_tests(
    *,
    curated: CuratedGitHubSource,
    date_from: str | None = None,
    date_to: str | None = None,
    min_rerun_passes: int | None = None,
    min_failed_prs: int | None = None,
    limit: int | None = None,
) -> FlakyTestList:
    parsed_from = _parse_date(curated.team, date_from or _DEFAULT_FLAKY_WINDOW)
    parsed_to = _parse_date(curated.team, date_to) if date_to else None
    span_days = ((parsed_to or datetime.now(tz=parsed_from.tzinfo)) - parsed_from).days
    if span_days > _MAX_FLAKY_WINDOW_DAYS:
        raise ValueError(f"date window spans {span_days} days; the maximum is {_MAX_FLAKY_WINDOW_DAYS}")
    min_rerun_passes = min_rerun_passes if min_rerun_passes is not None else _DEFAULT_FLAKY_MIN_RERUN_PASSES
    min_failed_prs = min_failed_prs if min_failed_prs is not None else _DEFAULT_FLAKY_MIN_FAILED_PRS
    # A zero threshold would make its HAVING arm trivially true and silently qualify every
    # test with any signal span — require an explicit positive bar instead.
    if min_rerun_passes < 1 or min_failed_prs < 1:
        raise ValueError("min_rerun_passes and min_failed_prs must be at least 1")
    limit = limit if limit is not None else _DEFAULT_FLAKY_LIMIT
    if not 1 <= limit <= _MAX_FLAKY_LIMIT:
        raise ValueError(f"limit must be between 1 and {_MAX_FLAKY_LIMIT}")
    return query_flaky_tests(
        curated=curated,
        date_from=parsed_from,
        date_to=parsed_to,
        min_rerun_passes=min_rerun_passes,
        min_failed_prs=min_failed_prs,
        limit=limit,
    )


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
