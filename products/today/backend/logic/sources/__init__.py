"""Every source the briefing reads. A failing source loses only its own items."""

import structlog

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from ..candidates import Candidate, SourceContext
from .alerts import AlertsSource
from .base import Source
from .dashboards import DashboardsSource
from .error_issues import ErrorIssuesSource
from .github import GitHubSource
from .reports import ReportsSource
from .support import SupportSource

logger = structlog.get_logger(__name__)

SOURCES: tuple[Source, ...] = (
    ReportsSource(),
    DashboardsSource(),
    AlertsSource(),
    SupportSource(),
    ErrorIssuesSource(),
    GitHubSource(),
)
SOURCES_BY_NAME: dict[str, Source] = {source.name: source for source in SOURCES}
if len(SOURCES_BY_NAME) != len(SOURCES):
    raise ValueError("Two briefing sources share a name; each name must be unique.")
SOURCE_NAMES: tuple[str, ...] = tuple(SOURCES_BY_NAME)


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
    for source in SOURCES:
        try:
            candidates.extend(source.collect(ctx))
        except Exception as error:
            logger.exception("today_source_failed", source=source.name, team_id=ctx.team.id)
            capture_exception(error, {"source": source.name, "team_id": ctx.team.id, "product": "today"})
            failed.append(source.name)
    return Collected(candidates=candidates, failed_sources=failed)
