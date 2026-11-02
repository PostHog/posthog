"""Facade for today. The only module other products and the presentation layer import."""

from posthog.models import Team, User

from products.signals.backend.facade import api as signals

from ..feature_flags import (
    is_enabled_for as is_enabled_for,
    may_ask_jev as may_ask_jev,
)
from ..logic import (
    code_excerpts,
    figure_sources,
    highlights,
    pulse_pins,
    report_page as report_pages,
)
from ..logic.jev import GatewayJev
from . import contracts


def delete_highlights_for_teams(team_ids: list[int]) -> None:
    """Remove every highlights row of the given teams. Called from team deletion, which no foreign key covers."""
    highlights.delete_for_teams(team_ids)


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


def get_highlights(*, team: Team, user: User, scopes: frozenset[str] | None) -> contracts.Highlights:
    return highlights.get_highlights(team=team, user=user, scopes=scopes)


def get_pulse_pins(*, team: Team, user: User, scopes: frozenset[str] | None) -> contracts.PulsePins:
    return contracts.PulsePins(pins=pulse_pins.get_pins(team=team, user_id=user.id, scopes=scopes))


def set_pulse_pins(*, team: Team, user: User, pins: list[contracts.PulsePin]) -> contracts.PulsePins:
    return contracts.PulsePins(pins=pulse_pins.set_pins(team=team, user_id=user.id, pins=pins))
