"""Orchestration for the DORA deploy-metrics read."""

from datetime import datetime
from typing import cast, get_args

from products.engineering_analytics.backend.facade.contracts import DoraOverview, UnknownDoraEnvironmentError
from products.engineering_analytics.backend.logic._shared import _DEFAULT_WINDOW, _parse_window
from products.engineering_analytics.backend.logic.queries._buckets import Granularity
from products.engineering_analytics.backend.logic.queries._curated import CuratedGitHubSource
from products.engineering_analytics.backend.logic.queries.dora import (
    query_dora_environment_choices,
    query_dora_overview,
)

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
    selected = None if environments is None else _known_environments(curated, environments, parsed_from, parsed_to)
    parsed_granularity: Granularity | None = None
    if granularity:
        if granularity not in _GRANULARITIES:
            raise ValueError(f"granularity must be one of {', '.join(_GRANULARITIES)}")
        parsed_granularity = cast(Granularity, granularity)
    return query_dora_overview(
        curated=curated,
        date_from=parsed_from,
        date_to=parsed_to,
        validated_environments=selected,
        github_team=(github_team or "").strip() or None,
        granularity=parsed_granularity,
    )


def _known_environments(
    curated: CuratedGitHubSource, requested: list[str], date_from: datetime, date_to: datetime | None
) -> list[str]:
    names = list(dict.fromkeys(name.strip() for name in requested))
    known = set(
        query_dora_environment_choices(curated=curated, environments=names, date_from=date_from, date_to=date_to)
    )
    unknown = [name for name in names if name not in known]
    if unknown:
        raise UnknownDoraEnvironmentError(unknown)
    return names
