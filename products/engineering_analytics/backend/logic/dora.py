"""Orchestration for the DORA deploy-metrics read."""

from products.engineering_analytics.backend.facade.contracts import DoraOverview
from products.engineering_analytics.backend.logic._shared import _DEFAULT_WINDOW, _parse_window
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.dora import query_dora_overview


def build_dora_overview(
    *,
    curated: CuratedGitHubSource,
    date_from: str | None = None,
    date_to: str | None = None,
    environment: str | None = None,
    github_team: str | None = None,
) -> DoraOverview:
    parsed_from, parsed_to = _parse_window(curated.team, date_from, date_to, default=_DEFAULT_WINDOW)
    return query_dora_overview(
        curated=curated,
        date_from=parsed_from,
        date_to=parsed_to,
        # Blank means "no filter", matching the branch-filter convention.
        environment=(environment or "").strip() or None,
        github_team=(github_team or "").strip() or None,
    )
