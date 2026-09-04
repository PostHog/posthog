"""Orchestration for the DORA deploy-metrics read."""

from typing import cast, get_args

from products.engineering_analytics.backend.facade.contracts import DoraOverview
from products.engineering_analytics.backend.logic._shared import _DEFAULT_WINDOW, _parse_window
from products.engineering_analytics.backend.logic.queries._buckets import Granularity
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.dora import query_dora_overview

_GRANULARITIES: tuple[Granularity, ...] = get_args(Granularity)


def build_dora_overview(
    *,
    curated: CuratedGitHubSource,
    date_from: str | None = None,
    date_to: str | None = None,
    environments: list[str] | None = None,
    github_team: str | None = None,
    granularity: str | None = None,
) -> DoraOverview:
    parsed_from, parsed_to = _parse_window(curated.team, date_from, date_to, default=_DEFAULT_WINDOW)
    parsed_granularity: Granularity | None = None
    if granularity:
        if granularity not in _GRANULARITIES:
            raise ValueError(f"granularity must be one of {', '.join(_GRANULARITIES)}")
        parsed_granularity = cast(Granularity, granularity)
    # Blank means "no filter", matching the branch-filter convention.
    environments_filter = [name.strip() for name in (environments or []) if name.strip()]
    return query_dora_overview(
        curated=curated,
        date_from=parsed_from,
        date_to=parsed_to,
        environments_filter=environments_filter or None,
        github_team=(github_team or "").strip() or None,
        granularity=parsed_granularity,
    )
