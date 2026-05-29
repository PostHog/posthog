"""Facade for engineering_analytics.

The ONLY module other products (and the DRF presentation layer) import. Public
functions take a team plus PostHog-convention parameters and return canonical
contract types.

``date_from`` / ``date_to`` follow the posthog/schema.py convention: a relative
string like ``-7d`` or an ISO8601 timestamp, with ``date_from`` defaulting to
``-7d`` and ``date_to=None`` meaning "now". ``repo`` is an optional ``owner/name``
filter; in v1 it only labels the response (warehouse rows carry no repo column).
"""

from posthog.models.team import Team

from products.engineering_analytics.backend import logic
from products.engineering_analytics.backend.facade.contracts import PRLifecycle, TimeToMerge, WorkflowReport


def get_workflow_report(
    *,
    team: Team,
    date_from: str = "-7d",
    date_to: str | None = None,
    repo: str | None = None,
) -> WorkflowReport:
    return logic.build_workflow_report(team=team, date_from=date_from, date_to=date_to, repo=repo)


def get_time_to_merge(
    *,
    team: Team,
    date_from: str = "-7d",
    date_to: str | None = None,
    repo: str | None = None,
    group_by_author: bool = False,
) -> TimeToMerge:
    return logic.build_time_to_merge(
        team=team,
        date_from=date_from,
        date_to=date_to,
        repo=repo,
        group_by_author=group_by_author,
    )


def get_pr_lifecycle(
    *,
    team: Team,
    pr_number: int,
    repo: str | None = None,
) -> PRLifecycle | None:
    return logic.build_pr_lifecycle(team=team, pr_number=pr_number, repo=repo)
