"""Facade for engineering_analytics.

The ONLY module other products (and the DRF presentation layer) import for
runtime PR/CI analytics. Public functions take a team plus PostHog-convention
parameters and return canonical contract types.

``repo`` is an optional ``owner/name`` filter, applied against the read layer's
repo identity (mapped from ``base.repo.full_name``).
"""

from posthog.models.team import Team

from products.engineering_analytics.backend import logic
from products.engineering_analytics.backend.facade.contracts import PRLifecycle


def get_pr_lifecycle(
    *,
    team: Team,
    pr_number: int,
    repo: str | None = None,
) -> PRLifecycle | None:
    return logic.build_pr_lifecycle(team=team, pr_number=pr_number, repo=repo)
