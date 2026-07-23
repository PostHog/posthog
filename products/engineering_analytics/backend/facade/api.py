"""Facade for engineering_analytics.

The ONLY module other products (and the DRF presentation layer) import for
runtime PR/CI analytics. Public functions take a team plus PostHog-convention
parameters and return canonical contract types.

``repo`` is an optional ``owner/name`` filter, applied against the curated repo
identity (mapped from ``base.repo.full_name``). ``branch`` is an optional exact
``head_branch`` filter for workflow health, a workflow's runs list, and its runner
costs; workflow health additionally takes a broader ``run_scope`` filter
(``pull_request`` scopes to PR-attributed runs). ``date_from`` / ``date_to`` accept
relative strings (``-30d``) or ISO8601 and are resolved against the team timezone.
``source_id`` selects a specific connected GitHub source when the team has more than
one; it defaults to the oldest connected source. ``user_access_control`` enforces the
requesting user's per-source warehouse access (pass the request's; ``None`` for system
contexts). Each function resolves the team's authorized curated read handle once, here,
then delegates to the read layer — source selection and access control live in this layer,
not in the query builders below it.
"""

from typing import TYPE_CHECKING

from posthog.models.team import Team

from products.engineering_analytics.backend import logic
from products.engineering_analytics.backend.facade.contracts import (
    BranchPRMatch,
    BrokenTestsResult,
    CICardSummary,
    CIFailureLogs,
    CurrentBranchHealth,
    FlakyTestList,
    GitHubSource,
    MasterFailureGroup,
    PRCostSummary,
    PRLifecycle,
    PullRequestList,
    QuarantineFile,
    QuarantineRequest,
    QuarantineRequestResult,
    RepoOverview,
    RunFailureLogs,
    TeamCIActivity,
    TeamCIHealthList,
    TeamMergeTrend,
    WorkflowCost,
    WorkflowHealthItem,
    WorkflowJob,
    WorkflowJobAggregate,
    WorkflowRunActivity,
    WorkflowRunDetail,
    WorkflowRunnerCost,
)

if TYPE_CHECKING:
    from datetime import datetime

    from posthog.rbac.user_access_control import UserAccessControl

    from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource


def _authorized_source(
    team: Team,
    source_id: str | None,
    user_access_control: "UserAccessControl | None",
    repo: str | None = None,
) -> "CuratedGitHubSource":
    """Resolve this caller's curated read handle — the single place source selection and per-source
    warehouse access control happen. ``user_access_control`` (None for system/Temporal/CLI contexts)
    filters out sources the requesting user can't access; ``source_id`` selects a specific source,
    else the oldest connected. ``repo`` ('owner/name'), when the caller already scopes to one repo,
    prefers the source connected for that repo — so a team with one source per repository reads the
    right one. Raises ``GitHubSourceNotConnectedError`` / ``ValueError`` (bad source_id).
    """
    return logic.CuratedGitHubSource.for_team(
        team, source_id=source_id, repo=repo, user_access_control=user_access_control
    )


def get_pr_lifecycle(
    *,
    team: Team,
    pr_number: int,
    repo: str,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> PRLifecycle | None:
    return logic.build_pr_lifecycle(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo), pr_number=pr_number, repo=repo
    )


def get_pr_cost(
    *,
    team: Team,
    pr_number: int,
    repo: str,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> PRCostSummary:
    return logic.build_pr_cost(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo), pr_number=pr_number, repo=repo
    )


def get_workflow_run(
    *,
    team: Team,
    run_id: int,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> WorkflowRunDetail | None:
    return logic.build_workflow_run(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo), run_id=run_id
    )


def list_pr_runs(
    *,
    team: Team,
    pr_number: int,
    repo: str,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> list[WorkflowRunDetail]:
    return logic.build_pr_runs(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo), pr_number=pr_number, repo=repo
    )


def resolve_branch(
    *,
    team: Team,
    branch: str | None = None,
    repo: str | None = None,
    timestamp: "datetime | None" = None,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> list[BranchPRMatch]:
    """Resolve a git branch to the pull request(s) it belongs to — the cross-product link seam
    (LLM analytics links a git branch to a PR detail page). ``branch`` is required; ``repo``
    ('owner/name') optionally narrows to one repository. ``timestamp`` (the trace's capture time)
    prefers the PR that was active at that moment when a branch name was reused across PRs over
    time — a ranking hint only, never a filter.
    """
    return logic.build_resolve_branch(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
        branch=branch,
        repo=repo,
        timestamp=timestamp,
    )


def get_ci_failure_logs(
    *,
    team: Team,
    pr_number: int,
    repo: str,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> CIFailureLogs:
    return logic.build_ci_failure_logs(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo), pr_number=pr_number, repo=repo
    )


def list_workflow_runs(
    *,
    team: Team,
    repo: str,
    workflow_name: str,
    date_from: str | None = None,
    date_to: str | None = None,
    branch: str | None = None,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> list[WorkflowRunDetail]:
    return logic.build_workflow_run_list(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
        repo=repo,
        workflow_name=workflow_name,
        date_from=date_from,
        date_to=date_to,
        branch=branch,
    )


def get_workflow_run_activity(
    *,
    team: Team,
    repo: str,
    workflow_name: str,
    date_from: str | None = None,
    date_to: str | None = None,
    branch: str | None = None,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> WorkflowRunActivity:
    return logic.build_workflow_run_activity(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
        repo=repo,
        workflow_name=workflow_name,
        date_from=date_from,
        date_to=date_to,
        branch=branch,
    )


def get_workflow_runner_costs(
    *,
    team: Team,
    repo: str,
    workflow_name: str,
    date_from: str | None = None,
    date_to: str | None = None,
    branch: str | None = None,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> list[WorkflowRunnerCost]:
    return logic.build_workflow_runner_costs(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
        repo=repo,
        workflow_name=workflow_name,
        date_from=date_from,
        date_to=date_to,
        branch=branch,
    )


def list_author_workflow_costs(
    *,
    team: Team,
    author: str,
    date_from: str | None = None,
    date_to: str | None = None,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> list[WorkflowCost]:
    return logic.build_author_workflow_costs(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
        author=author,
        date_from=date_from,
        date_to=date_to,
    )


def list_workflow_jobs(
    *,
    team: Team,
    run_id: int,
    run_attempt: int | None = None,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> list[WorkflowJob]:
    return logic.build_workflow_jobs(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
        run_id=run_id,
        run_attempt=run_attempt,
    )


def get_ci_cards(
    *,
    team: Team,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> CICardSummary:
    return logic.build_ci_cards(curated=_authorized_source(team, source_id, user_access_control, repo=repo))


def list_pull_requests(
    *,
    team: Team,
    date_from: str | None = None,
    author: str | None = None,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> PullRequestList:
    return logic.build_pull_request_list(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo), date_from=date_from, author=author
    )


def list_workflow_health(
    *,
    team: Team,
    date_from: str | None = None,
    date_to: str | None = None,
    branch: str | None = None,
    run_scope: str | None = None,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> list[WorkflowHealthItem]:
    return logic.build_workflow_health(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
        date_from=date_from,
        date_to=date_to,
        branch=branch,
        run_scope=run_scope,
    )


def list_flaky_tests(
    *,
    team: Team,
    date_from: str | None = None,
    date_to: str | None = None,
    min_failed_prs: int | None = None,
    limit: int | None = None,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> FlakyTestList:
    return logic.build_flaky_tests(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
        date_from=date_from,
        date_to=date_to,
        min_failed_prs=min_failed_prs,
        limit=limit,
    )


def list_team_ci_health(
    *,
    team: Team,
    date_from: str | None = None,
    date_to: str | None = None,
    min_failed_prs: int | None = None,
    limit: int | None = None,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> TeamCIHealthList:
    return logic.build_team_ci_health(
        curated=_authorized_source(team, source_id, user_access_control),
        date_from=date_from,
        date_to=date_to,
        min_failed_prs=min_failed_prs,
        limit=limit,
    )


def get_team_ci_activity(
    *,
    team: Team,
    owner_team: str,
    date_from: str | None = None,
    date_to: str | None = None,
    test_limit: int | None = None,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> TeamCIActivity:
    return logic.build_team_ci_activity(
        curated=_authorized_source(team, source_id, user_access_control),
        owner_team=owner_team,
        date_from=date_from,
        date_to=date_to,
        test_limit=test_limit,
    )


def get_team_merge_trend(
    *,
    team: Team,
    owner_team: str,
    date_from: str | None = None,
    date_to: str | None = None,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> TeamMergeTrend:
    return logic.build_team_merge_trend(
        curated=_authorized_source(team, source_id, user_access_control),
        owner_team=owner_team,
        date_from=date_from,
        date_to=date_to,
    )


def get_broken_tests(
    *,
    team: Team,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> BrokenTestsResult:
    return logic.build_broken_tests(curated=_authorized_source(team, source_id, user_access_control, repo=repo))


def list_github_sources(*, team: Team, user_access_control: "UserAccessControl | None" = None) -> list[GitHubSource]:
    return logic.build_github_sources(team=team, user_access_control=user_access_control)


def get_quarantine(
    *,
    team: Team,
    repo: str | None = None,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> QuarantineFile:
    # Quarantine resolves its source lazily (DEBUG reads the local checkout, an explicit ``repo`` needs
    # no source) so it stays fail-open where the curated reads above don't — ``source_id`` /
    # ``user_access_control`` only matter when it falls back to the connected source's most-active repo.
    return logic.build_quarantine(team=team, repo=repo, source_id=source_id, user_access_control=user_access_control)


def request_quarantine(
    *,
    team: Team,
    request: QuarantineRequest,
    user_access_control: "UserAccessControl | None" = None,
) -> QuarantineRequestResult:
    return logic.request_quarantine(team=team, request=request, user_access_control=user_access_control)


def get_repo_overview(
    *,
    team: Team,
    date_from: str | None = None,
    date_to: str | None = None,
    include_series: bool = True,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> RepoOverview:
    return logic.build_repo_overview(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
        date_from=date_from,
        date_to=date_to,
        include_series=include_series,
    )


def get_current_branch_health(
    *,
    team: Team,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> CurrentBranchHealth:
    return logic.build_current_branch_health(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo)
    )


def get_repo_run_activity(
    *,
    team: Team,
    date_from: str | None = None,
    date_to: str | None = None,
    branch: str | None = None,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> WorkflowRunActivity:
    return logic.build_repo_run_activity(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
        date_from=date_from,
        date_to=date_to,
        branch=branch,
    )


def list_master_failures(
    *,
    team: Team,
    date_from: str | None = None,
    date_to: str | None = None,
    branch: str | None = None,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> list[MasterFailureGroup]:
    return logic.build_master_failures(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
        date_from=date_from,
        date_to=date_to,
        branch=branch,
    )


def get_run_failure_logs(
    *,
    team: Team,
    run_id: int,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> RunFailureLogs:
    return logic.build_run_failure_logs(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo), run_id=run_id
    )


def list_job_aggregates(
    *,
    team: Team,
    workflow_name: str,
    date_from: str | None = None,
    date_to: str | None = None,
    branch: str | None = None,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> list[WorkflowJobAggregate]:
    return logic.build_job_aggregates(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
        workflow_name=workflow_name,
        date_from=date_from,
        date_to=date_to,
        branch=branch,
    )
