"""Facade for engineering_analytics.

The ONLY module other products (and the DRF presentation layer) import for
runtime PR/CI analytics. Public functions take a team plus PostHog-convention
parameters and return canonical contract types.

``repo`` is an optional ``owner/name`` filter, applied against the curated repo
identity (mapped from ``base.repo.full_name``). ``date_from`` / ``date_to`` accept
relative strings (``-30d``) or ISO8601 and are resolved against the team timezone.
``source_id`` selects a specific connected GitHub source when the team has more than
one; it defaults to the oldest connected source.
"""

from posthog.models.team import Team

from products.engineering_analytics.backend import logic
from products.engineering_analytics.backend.facade.contracts import (
    CICardSummary,
    PRLifecycle,
    PullRequestList,
    WorkflowHealthItem,
)


def get_pr_lifecycle(
    *,
    team: Team,
    pr_number: int,
    repo: str | None = None,
    source_id: str | None = None,
) -> PRLifecycle | None:
    return logic.build_pr_lifecycle(team=team, pr_number=pr_number, repo=repo, source_id=source_id)


def get_ci_cards(*, team: Team, source_id: str | None = None) -> CICardSummary:
    return logic.build_ci_cards(team=team, source_id=source_id)


def list_pull_requests(
    *,
    team: Team,
    date_from: str | None = None,
    source_id: str | None = None,
) -> PullRequestList:
    return logic.build_pull_request_list(team=team, date_from=date_from, source_id=source_id)


def list_workflow_health(
    *,
    team: Team,
    date_from: str | None = None,
    date_to: str | None = None,
    source_id: str | None = None,
) -> list[WorkflowHealthItem]:
    return logic.build_workflow_health(team=team, date_from=date_from, date_to=date_to, source_id=source_id)
