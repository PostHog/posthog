"""Facade for engineering_analytics — the only module other products and the DRF layer import.

Public functions take a team plus PostHog-convention params and return canonical contracts. Param
contracts: ``repo`` is an optional ``owner/name`` filter; ``branch`` an exact ``head_branch`` filter
(workflow health); ``date_from`` / ``date_to`` accept relative strings (``-30d``) or ISO8601, resolved
against the team timezone; ``source_id`` selects a connected GitHub source (defaults to the oldest);
``user_access_control`` enforces the requesting user's per-source warehouse access (``None`` for system
contexts). Each function resolves the authorized curated read handle once here — source selection and
access control live in this layer, not the query builders.
"""

from typing import TYPE_CHECKING

from posthog.models.team import Team

from products.engineering_analytics.backend import logic
from products.engineering_analytics.backend.facade.contracts import (
    CICardSummary,
    GitHubSource,
    PRCostSummary,
    PRLifecycle,
    PullRequestList,
    QuarantineFile,
    WorkflowHealthItem,
    WorkflowJob,
    WorkflowRunDetail,
    WorkflowRunnerCost,
)

if TYPE_CHECKING:
    from posthog.rbac.user_access_control import UserAccessControl

    from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource


def _authorized_source(
    team: Team, source_id: str | None, user_access_control: "UserAccessControl | None"
) -> "CuratedGitHubSource":
    """Resolve the caller's curated read handle — the one place source selection and per-source access
    control happen. Raises ``GitHubSourceNotConnectedError`` / ``ValueError`` (bad source_id).
    """
    return logic.CuratedGitHubSource.for_team(team, source_id=source_id, user_access_control=user_access_control)


def get_pr_lifecycle(
    *,
    team: Team,
    pr_number: int,
    repo: str,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> PRLifecycle | None:
    return logic.build_pr_lifecycle(
        curated=_authorized_source(team, source_id, user_access_control), pr_number=pr_number, repo=repo
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
        curated=_authorized_source(team, source_id, user_access_control), pr_number=pr_number, repo=repo
    )


def get_workflow_run(
    *,
    team: Team,
    run_id: int,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> WorkflowRunDetail | None:
    return logic.build_workflow_run(curated=_authorized_source(team, source_id, user_access_control), run_id=run_id)


def list_pr_runs(
    *,
    team: Team,
    pr_number: int,
    repo: str,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> list[WorkflowRunDetail]:
    return logic.build_pr_runs(
        curated=_authorized_source(team, source_id, user_access_control), pr_number=pr_number, repo=repo
    )


def list_workflow_runs(
    *,
    team: Team,
    repo: str,
    workflow_name: str,
    date_from: str | None = None,
    date_to: str | None = None,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> list[WorkflowRunDetail]:
    return logic.build_workflow_run_list(
        curated=_authorized_source(team, source_id, user_access_control),
        repo=repo,
        workflow_name=workflow_name,
        date_from=date_from,
        date_to=date_to,
    )


def get_workflow_runner_costs(
    *,
    team: Team,
    repo: str,
    workflow_name: str,
    date_from: str | None = None,
    date_to: str | None = None,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> list[WorkflowRunnerCost]:
    return logic.build_workflow_runner_costs(
        curated=_authorized_source(team, source_id, user_access_control),
        repo=repo,
        workflow_name=workflow_name,
        date_from=date_from,
        date_to=date_to,
    )


def list_workflow_jobs(
    *,
    team: Team,
    run_id: int,
    run_attempt: int | None = None,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> list[WorkflowJob]:
    return logic.build_workflow_jobs(
        curated=_authorized_source(team, source_id, user_access_control), run_id=run_id, run_attempt=run_attempt
    )


def get_ci_cards(
    *, team: Team, source_id: str | None = None, user_access_control: "UserAccessControl | None" = None
) -> CICardSummary:
    return logic.build_ci_cards(curated=_authorized_source(team, source_id, user_access_control))


def list_pull_requests(
    *,
    team: Team,
    date_from: str | None = None,
    author: str | None = None,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> PullRequestList:
    return logic.build_pull_request_list(
        curated=_authorized_source(team, source_id, user_access_control), date_from=date_from, author=author
    )


def list_workflow_health(
    *,
    team: Team,
    date_from: str | None = None,
    date_to: str | None = None,
    branch: str | None = None,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> list[WorkflowHealthItem]:
    return logic.build_workflow_health(
        curated=_authorized_source(team, source_id, user_access_control),
        date_from=date_from,
        date_to=date_to,
        branch=branch,
    )


def list_github_sources(*, team: Team, user_access_control: "UserAccessControl | None" = None) -> list[GitHubSource]:
    return logic.build_github_sources(team=team, user_access_control=user_access_control)


def get_quarantine(
    *,
    team: Team,
    repo: str | None = None,
    source_id: str | None = None,
    user_access_control: "UserAccessControl | None" = None,
) -> QuarantineFile:
    # Quarantine resolves its source lazily and stays fail-open (unlike the curated reads): source_id /
    # user_access_control only matter when it falls back to the connected source's most-active repo.
    return logic.build_quarantine(team=team, repo=repo, source_id=source_id, user_access_control=user_access_control)
