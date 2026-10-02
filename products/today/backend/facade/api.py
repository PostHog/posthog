"""Facade for today. The only module other products and the presentation layer import."""

from posthog.models import Team, User

from products.signals.backend.facade import api as signals

from ..feature_flags import may_get_briefing as may_get_briefing
from ..logic import briefings
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
    """Remove every briefing of the given teams. Called from team deletion, which no foreign key covers."""
    briefings.delete_for_teams(team_ids)


def list_candidates(*, team: Team, user: User, timezone_name: str | None) -> contracts.CandidateList:
    """Today's ranked items with their facts and reasons, without the written text."""
    return briefings.list_candidates(team=team, user=user, timezone_name=timezone_name)
