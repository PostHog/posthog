"""Orchestration for engineering_analytics.

Resolves caller inputs (date strings, ``owner/name`` repo), binds the team to its curated read layer
(``CuratedGitHubSource``), and returns canonical contracts. The curated builders (``backend/logic/views``)
own all GitHub-shaped mapping; this layer deals only in canonical types.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from posthog.models.team import Team
from posthog.utils import relative_date_parse

from products.engineering_analytics.backend.facade.contracts import (
    CICardSummary,
    GitHubSource,
    PRCostSummary,
    PRLifecycle,
    PullRequestList,
    WorkflowHealthItem,
    WorkflowJob,
    WorkflowRunDetail,
    WorkflowRunnerCost,
)
from products.engineering_analytics.backend.logic.quarantine import build_quarantine as build_quarantine
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.ci_cards import query_ci_cards
from products.engineering_analytics.backend.logic.queries.pr_cost import query_pr_cost, query_workflow_runner_costs
from products.engineering_analytics.backend.logic.queries.pr_lifecycle import query_pr_lifecycle
from products.engineering_analytics.backend.logic.queries.pr_runs import query_pr_runs
from products.engineering_analytics.backend.logic.queries.pull_request_list import query_pull_request_list
from products.engineering_analytics.backend.logic.queries.workflow_health import query_workflow_health
from products.engineering_analytics.backend.logic.queries.workflow_jobs import query_workflow_jobs
from products.engineering_analytics.backend.logic.queries.workflow_run import query_workflow_run
from products.engineering_analytics.backend.logic.queries.workflow_run_list import query_workflow_run_list
from products.engineering_analytics.backend.logic.sources import list_github_sources

if TYPE_CHECKING:
    from posthog.rbac.user_access_control import UserAccessControl

# Default recency window when a caller omits date_from.
_DEFAULT_WINDOW = "-30d"

# Tighter window than the PR backlog — CI health is a "right now" question, and the short window
# buckets by hour for a live-looking trend.
_DEFAULT_WORKFLOW_WINDOW = "-24h"

# workflow_health zero-fills one entry per workflow per day, so an unbounded range would materialize
# an enormous response. A year is plenty for trends.
_MAX_WINDOW_DAYS = 366


# Each builder operates on an already-resolved CuratedGitHubSource (source selection + access control
# happened once at the facade); they validate their own inputs and read through the handle.
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
    )


def build_workflow_runner_costs(
    *,
    curated: CuratedGitHubSource,
    repo: str | None,
    workflow_name: str,
    date_from: str | None = None,
    date_to: str | None = None,
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
    )


def build_ci_cards(*, curated: CuratedGitHubSource) -> CICardSummary:
    return query_ci_cards(curated=curated)


# Listing sources is its own concern (no curated read handle): threads the user's access control so
# the picker can't enumerate sources the user can't access.
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
    # A half-specified repo would otherwise drop the filter silently and return a PR from the wrong
    # repo — fail loudly instead.
    if not (owner and name):
        raise ValueError(f"repo must be in 'owner/name' format, got: {repo!r}")
    return owner, name
