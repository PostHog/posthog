"""PR-scoped orchestration: lifecycle, runs, logs, cost, backlog cards, and lists."""

from dataclasses import replace
from datetime import datetime

import structlog

from products.engineering_analytics.backend.facade.contracts import (
    BranchPRMatch,
    CICardSummary,
    CIFailureLogs,
    MergedPullRequest,
    PRCostSummary,
    PRLifecycle,
    PullRequestList,
    WorkflowCost,
    WorkflowRunDetail,
)
from products.engineering_analytics.backend.logic._shared import (
    _DEFAULT_WINDOW,
    _parse_date,
    _parse_window,
    _require_repo,
    _split_repo,
)
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.ci_cards import query_ci_cards
from products.engineering_analytics.backend.logic.queries.ci_failure_logs import query_ci_failure_logs
from products.engineering_analytics.backend.logic.queries.llm_spend import query_pr_llm_spend
from products.engineering_analytics.backend.logic.queries.merged_pull_requests import query_merged_pull_requests
from products.engineering_analytics.backend.logic.queries.pr_cost import query_author_workflow_costs, query_pr_cost
from products.engineering_analytics.backend.logic.queries.pr_lifecycle import query_pr_lifecycle
from products.engineering_analytics.backend.logic.queries.pr_runs import query_pr_runs
from products.engineering_analytics.backend.logic.queries.pull_request_list import query_pull_request_list
from products.engineering_analytics.backend.logic.queries.resolve_branch import query_resolve_branch

logger = structlog.get_logger(__name__)


def build_pr_lifecycle(*, curated: CuratedGitHubSource, pr_number: int, repo: str | None) -> PRLifecycle | None:
    owner, name = _require_repo(repo)
    return query_pr_lifecycle(curated=curated, pr_number=pr_number, repo_owner=owner, repo_name=name)


def build_pr_runs(*, curated: CuratedGitHubSource, pr_number: int, repo: str | None) -> list[WorkflowRunDetail]:
    owner, name = _require_repo(repo)
    return query_pr_runs(curated=curated, pr_number=pr_number, repo_owner=owner, repo_name=name)


def build_resolve_branch(
    *, curated: CuratedGitHubSource, branch: str | None, repo: str | None, timestamp: datetime | None = None
) -> list[BranchPRMatch]:
    resolved_branch = (branch or "").strip()
    if not resolved_branch:
        raise ValueError("provide a branch to resolve")
    # repo is an optional narrowing filter: absent -> (None, None); malformed (bare org) -> raises.
    owner, name = _split_repo(repo)
    # timestamp (the trace's capture time) only reorders results toward the PR active then; never filters.
    return query_resolve_branch(
        curated=curated, branch=resolved_branch, repo_owner=owner, repo_name=name, timestamp=timestamp
    )


def build_ci_failure_logs(*, curated: CuratedGitHubSource, pr_number: int, repo: str | None) -> CIFailureLogs:
    owner, name = _require_repo(repo)
    return query_ci_failure_logs(curated=curated, pr_number=pr_number, repo_owner=owner, repo_name=name)


def build_pr_cost(*, curated: CuratedGitHubSource, pr_number: int, repo: str | None) -> PRCostSummary:
    owner, name = _require_repo(repo)
    # LLM token spend is an additive component joined by branch from the events table, merged onto the
    # CI cost summary. Kept sequential: HogQL table resolution reads warehouse metadata through the
    # request's DB connection, which worker threads don't share.
    summary = query_pr_cost(curated=curated, pr_number=pr_number, repo_owner=owner, repo_name=name)
    # The spend join scans the events table across the PR's whole lifetime, so a long-lived PR on an
    # AI-heavy team can time out; the enrichment is optional, so it degrades to null instead of
    # taking the whole cost summary down with it.
    try:
        llm_spend = query_pr_llm_spend(curated=curated, pr_number=pr_number, repo_owner=owner, repo_name=name)
    except Exception:
        logger.warning("engineering_analytics.pr_llm_spend_failed", pr_number=pr_number, exc_info=True)
        llm_spend = None
    return replace(summary, llm_spend=llm_spend)


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


def build_pull_request_list(
    *, curated: CuratedGitHubSource, date_from: str | None = None, author: str | None = None
) -> PullRequestList:
    parsed_from = _parse_date(curated.team, date_from or _DEFAULT_WINDOW)
    return query_pull_request_list(curated=curated, date_from=parsed_from, author=author)


def build_merged_pull_requests(
    *, curated: CuratedGitHubSource, repo: str, since: datetime, numbers: list[int] | None = None
) -> list[MergedPullRequest]:
    owner, name = _require_repo(repo)
    return query_merged_pull_requests(curated=curated, repo_owner=owner, repo_name=name, since=since, numbers=numbers)
