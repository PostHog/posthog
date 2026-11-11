"""The only module other products and the DRF presentation layer import for PR and CI analytics.

Shared parameters: ``repo`` is ``owner/name``. ``date_from`` / ``date_to`` accept relative strings
(``-30d``) or ISO8601, resolved in the team timezone. ``source_id`` selects one connected GitHub
source and defaults to the oldest synced one. ``user_access_control`` enforces the requesting user's
per-source warehouse access, and ``None`` is for system contexts. Source selection and access
control happen here, not in the query builders.
"""

from typing import TYPE_CHECKING

from posthog.models.team import Team

from products.engineering_analytics.backend import logic
from products.engineering_analytics.backend.facade.contracts import (
    AttentionPullRequestList,
    AuthorFrictionDetail,
    AuthorFrictionList,
    AuthorLLMSpendList,
    BranchPRMatch,
    BrokenTestsResult,
    CICardSummary,
    CIDataFreshness,
    CIEngine,
    CIFailureLogs,
    CISignalsConfig,
    CITestRunner,
    CITimingContext,
    CITimingKind,
    CurrentBranchHealth,
    DeliveryComparison,
    DeliverySummary,
    DepotCIRepoUsage,
    DoraOverview,
    FlakyTestList,
    GitHubSource,
    GitHubTeamRoster,
    JobLogInsights,
    LLMSpendCoverage,
    MasterFailureGroup,
    MergedPullRequest,
    PRCostSummary,
    PRLifecycle,
    PullRequestFrictionDetail,
    PullRequestList,
    PullRequestTimelines,
    QuarantineFile,
    QuarantineRequest,
    QuarantineRequestResult,
    RepoOverview,
    RunFailureLogs,
    TeamCIActivity,
    TeamCIHealthList,
    TeamMergeTrend,
    TrunkQuarantineDebt,
    WorkflowCost,
    WorkflowHealthItem,
    WorkflowJob,
    WorkflowJobAggregate,
    WorkflowRunActivity,
    WorkflowRunDetail,
    WorkflowRunnerCost,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from products.access_control.backend.facade.user_access_control import UserAccessControl
    from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource


def _authorized_source(
    team: Team,
    source_id: str | None,
    user_access_control: "UserAccessControl | None",
    repo: str | None = None,
    *,
    query_limit: int | None = None,
) -> "CuratedGitHubSource":
    """``repo`` prefers the source connected for that repository when ``source_id`` is not given.
    Raises ``GitHubSourceNotConnectedError``, or ``ValueError`` for a bad ``source_id``.
    """
    return logic.CuratedGitHubSource.for_team(
        team, source_id=source_id, repo=repo, user_access_control=user_access_control, query_limit=query_limit
    )


def enable(*, team: Team) -> None:
    """Opt the team in. Idempotent."""
    logic.enroll(team)


def get_ci_signals_config(*, team: Team, user_access_control: "UserAccessControl | None" = None) -> CISignalsConfig:
    return logic.get_ci_signals_config(team=team, user_access_control=user_access_control)


def update_ci_signals_config(
    *,
    team: Team,
    enabled: bool,
    created_by_id: int,
    user_access_control: "UserAccessControl | None" = None,
) -> CISignalsConfig:
    return logic.update_ci_signals_config(
        team=team, enabled=enabled, created_by_id=created_by_id, user_access_control=user_access_control
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
    ci_engine: CIEngine | None = None,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> WorkflowRunDetail | None:
    return logic.build_workflow_run(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo), run_id=run_id, ci_engine=ci_engine
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
    """The pull requests a git branch belongs to. ``branch`` is required. ``timestamp`` ranks the PR
    that was active at that moment first when a branch name was reused, and it never filters.
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
    run_scope: str | None = None,
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
        run_scope=run_scope,
    )


def get_workflow_run_activity(
    *,
    team: Team,
    repo: str,
    workflow_name: str,
    date_from: str | None = None,
    date_to: str | None = None,
    branch: str | None = None,
    run_scope: str | None = None,
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
        run_scope=run_scope,
    )


def get_workflow_runner_costs(
    *,
    team: Team,
    repo: str,
    workflow_name: str,
    date_from: str | None = None,
    date_to: str | None = None,
    branch: str | None = None,
    run_scope: str | None = None,
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
        run_scope=run_scope,
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


def list_author_llm_spend(
    *,
    team: Team,
    author: str,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int | None = None,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> AuthorLLMSpendList:
    return logic.build_author_llm_spend(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
        author=author,
        repo=repo,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )


def get_llm_spend_coverage(
    *,
    team: Team,
    date_from: str | None = None,
    date_to: str | None = None,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> LLMSpendCoverage:
    return logic.build_llm_spend_coverage(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
        repo=repo,
        date_from=date_from,
        date_to=date_to,
    )


def get_author_friction(
    *,
    team: Team,
    github_team: str | None = None,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> AuthorFrictionList:
    """``github_team`` lists only its members, with their repository-wide scores and ranks."""
    return logic.build_author_friction(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
        github_team=github_team.strip() if github_team and github_team.strip() else None,
    )


def get_author_friction_detail(
    *,
    team: Team,
    author: str,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> AuthorFrictionDetail:
    return logic.build_author_friction_detail(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo), author=author
    )


def get_pull_request_friction(
    *,
    team: Team,
    pr_number: int,
    repo: str,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> PullRequestFrictionDetail:
    return logic.build_pull_request_friction(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo), repo=repo, number=pr_number
    )


def get_delivery_summary(
    *,
    team: Team,
    author: str | None = None,
    github_team: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> DeliverySummary:
    """Takes exactly one of ``author`` or ``github_team``."""
    # Validate the scope before resolving the source, so a bad scope is not reported as a missing source.
    scope = logic.SummaryScope.from_params(author=author, github_team=github_team, pr_number=None, repo=None)
    return logic.build_delivery_summary(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
        scope=scope,
        date_from=date_from,
        date_to=date_to,
    )


def get_delivery_comparison(
    *,
    team: Team,
    author: str | None,
    pr_number: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> DeliveryComparison:
    """``pr_number`` names a pull request by the author, and needs ``repo``. A team that this pull
    request asked to review wins the team choice."""
    author = (author or "").strip()
    if not author:
        raise ValueError("author is required")
    repo = (repo or "").strip() or None
    # Pull request numbers restart in every repository, so a number alone names no pull request.
    if pr_number is not None and repo is None:
        raise ValueError("repo is required with pr_number")
    return logic.build_delivery_comparison(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
        author=author,
        focus_pr=pr_number,
        date_from=date_from,
        date_to=date_to,
    )


def get_pull_request_timelines(
    *,
    team: Team,
    author: str | None = None,
    github_team: str | None = None,
    pr_number: int | None = None,
    repo: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> PullRequestTimelines:
    """Takes exactly one of ``author``, ``github_team``, or ``pr_number`` (which needs ``repo``)."""
    # Validate the scope before resolving the source, so a bad scope is not reported as a missing source.
    scope = logic.DeliveryScope.from_params(author=author, github_team=github_team, pr_number=pr_number, repo=repo)
    return logic.build_pull_request_timelines(
        # One budget covers the PR batches and their evidence pages; exhaustion must not return partial totals.
        curated=_authorized_source(team, source_id, user_access_control, repo=repo, query_limit=100),
        scope=scope,
        date_from=date_from,
        date_to=date_to,
    )


def list_workflow_jobs(
    *,
    team: Team,
    run_id: int,
    ci_engine: CIEngine | None = None,
    run_attempt: int | None = None,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> list[WorkflowJob]:
    return logic.build_workflow_jobs(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
        run_id=run_id,
        ci_engine=ci_engine,
        run_attempt=run_attempt,
    )


def get_job_log_insights(
    *,
    team: Team,
    repo: str,
    run_id: int,
    job_id: int,
    ci_engine: CIEngine | None = None,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> JobLogInsights:
    return logic.build_job_log_insights(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
        run_id=run_id,
        job_id=job_id,
        ci_engine=ci_engine,
    )


def get_ci_data_freshness(
    *,
    team: Team,
    repo: str,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> CIDataFreshness:
    return logic.build_ci_data_freshness(curated=_authorized_source(team, source_id, user_access_control, repo=repo))


def get_ci_timing_context(
    *,
    team: Team,
    repo: str,
    ci_engine: CIEngine,
    run_id: int,
    run_attempt: int,
    kind: CITimingKind,
    job_ids: "Sequence[int]" = (),
    step_number: int | None = None,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> CITimingContext:
    return logic.build_ci_timing_context(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
        repo=repo,
        ci_engine=ci_engine,
        run_id=run_id,
        run_attempt=run_attempt,
        kind=kind,
        job_ids=job_ids,
        step_number=step_number,
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
    date_to: str | None = None,
    author: str | None = None,
    state: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> PullRequestList:
    return logic.build_pull_request_list(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
        date_from=date_from,
        date_to=date_to,
        author=author,
        state=state,
        limit=limit,
        offset=offset,
    )


def list_attention_pull_requests(
    *,
    team: Team,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> AttentionPullRequestList:
    return logic.build_attention_pull_requests(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo)
    )


def list_recently_merged_pull_requests(
    *,
    team: Team,
    repository: str,
    since: "datetime | None" = None,
    numbers: list[int] | None = None,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> list[MergedPullRequest]:
    """Merged pull requests in ``repository``, newest first. Raises ``GitHubSourceNotConnectedError``.

    ``numbers`` returns exactly those PRs whatever their merge date. ``since`` returns everything
    merged at or after a cutoff. They do not combine, and ``numbers`` wins if both are given.
    """
    return logic.build_merged_pull_requests(
        curated=_authorized_source(team, source_id, user_access_control, repo=repository),
        repo=repository,
        since=since,
        numbers=numbers,
    )


def list_workflow_health(
    *,
    team: Team,
    date_from: str | None = None,
    date_to: str | None = None,
    branch: str | None = None,
    run_scope: str | None = None,
    workflow_name: str | None = None,
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
        workflow_name=workflow_name,
    )


def list_flaky_tests(
    *,
    team: Team,
    date_from: str | None = None,
    date_to: str | None = None,
    min_failed_prs: int | None = None,
    limit: int | None = None,
    runner: CITestRunner | None = None,
    test: str | None = None,
    branch: str | None = None,
    pr_number: int | None = None,
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
        runner=runner,
        test=test,
        branch=branch,
        pr_number=pr_number,
    )


def list_team_ci_health(
    *,
    team: Team,
    date_from: str | None = None,
    date_to: str | None = None,
    min_failed_prs: int | None = None,
    limit: int | None = None,
    owner_team: str | None = None,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> TeamCIHealthList:
    return logic.build_team_ci_health(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
        date_from=date_from,
        date_to=date_to,
        min_failed_prs=min_failed_prs,
        limit=limit,
        owner_team=owner_team,
    )


def get_team_ci_activity(
    *,
    team: Team,
    owner_team: str,
    date_from: str | None = None,
    date_to: str | None = None,
    test_limit: int | None = None,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> TeamCIActivity:
    return logic.build_team_ci_activity(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
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
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> TeamMergeTrend:
    return logic.build_team_merge_trend(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
        owner_team=owner_team,
        date_from=date_from,
        date_to=date_to,
    )


def get_broken_tests(
    *,
    team: Team,
    test: str | None = None,
    branch: str | None = None,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> BrokenTestsResult:
    return logic.build_broken_tests(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo), test=test, branch=branch
    )


def list_github_sources(*, team: Team, user_access_control: "UserAccessControl | None" = None) -> list[GitHubSource]:
    return logic.build_github_sources(team=team, user_access_control=user_access_control)


def get_trunk_quarantine(
    *,
    team: Team,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> TrunkQuarantineDebt:
    return logic.build_trunk_quarantine(curated=_authorized_source(team, source_id, user_access_control, repo=repo))


def get_quarantine(
    *,
    team: Team,
    repo: str | None = None,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> QuarantineFile:
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


def get_dora_overview(
    *,
    team: Team,
    date_from: str | None = None,
    date_to: str | None = None,
    environments: list[str] | None = None,
    github_team: str | None = None,
    granularity: str | None = None,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> DoraOverview:
    """Raises ``UnknownDoraEnvironmentError`` when ``environments`` names an environment the source
    did not deploy to in the scan window."""
    return logic.build_dora_overview(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo),
        date_from=date_from,
        date_to=date_to,
        environments=environments,
        github_team=github_team,
        granularity=granularity,
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
    ci_engine: CIEngine | None = None,
    source_id: str | None = None,
    repo: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> RunFailureLogs:
    return logic.build_run_failure_logs(
        curated=_authorized_source(team, source_id, user_access_control, repo=repo), run_id=run_id, ci_engine=ci_engine
    )


def list_job_aggregates(
    *,
    team: Team,
    workflow_name: str,
    date_from: str | None = None,
    date_to: str | None = None,
    branch: str | None = None,
    run_scope: str | None = None,
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
        run_scope=run_scope,
    )


def get_github_team_roster(*, team: Team, user_access_control: "UserAccessControl | None" = None) -> GitHubTeamRoster:
    """Needs only the membership table, not the ``pull_requests`` / ``workflow_runs`` pair the other
    reads require. An unsynced snapshot comes back as ``synced=False``, never an error.
    """
    return logic.build_github_team_roster(team=team, user_access_control=user_access_control)


def get_depot_ci_usage(
    *,
    team: Team,
    date_from: str | None = None,
    date_to: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> list[DepotCIRepoUsage]:
    return logic.build_depot_ci_usage(
        team=team, date_from=date_from, date_to=date_to, user_access_control=user_access_control
    )
