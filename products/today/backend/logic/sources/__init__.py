"""Every source the briefing reads. A failing source loses only its own items."""

from collections.abc import Callable

import structlog

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from ..candidates import Candidate, SourceContext
from . import alerts, dashboards, error_issues, github, reports, support

logger = structlog.get_logger(__name__)

SOURCES: dict[str, Callable[[SourceContext], list[Candidate]]] = {
    "reports": reports.collect,
    "dashboards": dashboards.collect,
    "alerts": alerts.collect,
    "support": support.collect,
    "error_issues": error_issues.collect,
    "github": github.collect,
}
SOURCE_NAMES: tuple[str, ...] = tuple(SOURCES)


@frozen
class Collected:
    candidates: list[Candidate]
    failed_sources: list[str]


def collect_all(ctx: SourceContext) -> Collected:
    """Every source, one after the other, for the on-demand candidates API.

    Scheduled and first-open briefings run each source as its own Temporal activity instead.
    """
    candidates: list[Candidate] = []
    failed: list[str] = []
    for name, collect in SOURCES.items():
        try:
            candidates.extend(collect(ctx))
        except Exception as error:
            logger.exception("today_source_failed", source=name, team_id=ctx.team.id)
            capture_exception(error, {"source": name, "team_id": ctx.team.id, "product": "today"})
            failed.append(name)
    return Collected(candidates=candidates, failed_sources=failed)
