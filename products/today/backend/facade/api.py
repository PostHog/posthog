"""Facade for today. The only module other products and the presentation layer import."""

from posthog.models import Team, User

from products.signals.backend.facade import api as signals

from ..feature_flags import (
    is_enabled_for as is_enabled_for,
    may_ask_jev as may_ask_jev,
    may_get_briefing as may_get_briefing,
)
from ..logic import (
    briefings,
    code_excerpts,
    figure_sources,
    focus,
    report_page as report_pages,
)
from ..logic.jev import GatewayJev
from . import contracts
from .enums import BriefingStatus


def get_briefing(
    *, team: Team, user: User, timezone_name: str | None, metric_access: signals.ReportMetricAccessPolicy
) -> contracts.Briefing:
    """Today's briefing for the person. Starts generating one when there is none yet.

    `metric_access` is the request's access to report metrics, so report cards hide what the Inbox hides.
    """
    current = briefings.get_or_start_briefing(team=team, user=user, timezone_name=timezone_name)
    return briefings.to_contract(
        current.shown,
        team,
        user,
        metric_access=metric_access,
        status=BriefingStatus.WRITING if current.generating else None,
    )


def refresh_briefing(
    *, team: Team, user: User, timezone_name: str | None, metric_access: signals.ReportMetricAccessPolicy
) -> contracts.Briefing:
    """Regenerate today's briefing. The ready one stays until the new one is written."""
    briefings.refresh_briefing(team=team, user=user, timezone_name=timezone_name)
    return get_briefing(team=team, user=user, timezone_name=timezone_name, metric_access=metric_access)


def delete_briefings_for_teams(team_ids: list[int]) -> None:
    """Remove every briefing and focus of the given teams. Called from team deletion, which no foreign key covers."""
    briefings.delete_for_teams(team_ids)
    focus.delete_for_teams(team_ids)


def get_focus(*, team: Team, user: User) -> contracts.BriefingFocus:
    """What the person asked their briefing to show more or less of. Empty when they set nothing."""
    return focus.get_focus(team=team, user=user)


def set_focus(*, team: Team, user: User, topics: list[contracts.FocusTopic]) -> contracts.BriefingFocus:
    """Replace what the person asked their briefing to show more or less of."""
    return focus.set_focus(team=team, user=user, topics=topics)


def list_candidates(*, team: Team, user: User, timezone_name: str | None) -> contracts.CandidateList:
    """Today's ranked items with their facts and reasons, without the written text."""
    return briefings.list_candidates(team=team, user=user, timezone_name=timezone_name)


def _jev(team: Team, user: User, model: str | None = None) -> GatewayJev:
    return GatewayJev(team_id=team.id, distinct_id=str(user.distinct_id), model=model)


def report_key_clauses(
    *, team: Team, user: User, report_id: str, include_impact: bool
) -> contracts.ReportKeyClauses | None:
    page = signals.report_page_source(team=team, report_id=report_id, with_signals=False)
    return report_pages.key_clauses(page, include_impact, _jev(team, user)) if page is not None else None


def pick_code_excerpt(*, team: Team, user: User, finding: str, excerpts: list[str]) -> int | None:
    return code_excerpts.which_excerpt(finding, excerpts, _jev(team, user))


def report_page(*, team: Team, report_id: str) -> contracts.ReportPage | None:
    source = report_pages.page_source(team=team, report_id=report_id)
    return report_pages.report_page(source) if source is not None else None


def report_figure_marks(*, team: Team, user: User, report_id: str) -> list[contracts.FigureMark] | None:
    page = signals.report_page_source(team=team, report_id=report_id)
    if page is None:
        return None
    artefacts = signals.report_agent_texts(team=team, report_id=report_id, types=figure_sources.RESEARCH_TYPES)
    return report_pages.figure_marks(page, artefacts, _jev(team, user, figure_sources.FIGURE_MODEL))
