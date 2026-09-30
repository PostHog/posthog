"""Facade for today. The only module other products and the presentation layer import."""

from posthog.models import Team, User

from ..logic import briefings
from ..logic.eligibility import is_enabled_for as is_enabled_for
from . import contracts
from .contracts import RefreshLimitReached as RefreshLimitReached


def get_briefing(*, team: Team, user: User, timezone_name: str | None) -> contracts.Briefing:
    """Today's briefing for the person. Starts generating one when there is none yet."""
    briefing = briefings.get_or_start_briefing(team=team, user=user, timezone_name=timezone_name)
    return briefings.to_contract(briefing, team)


def refresh_briefing(*, team: Team, user: User, timezone_name: str | None) -> contracts.Briefing:
    """Start a new generation for today. Raises RefreshLimitReached after the daily limit."""
    briefings.refresh_briefing(team=team, user=user, timezone_name=timezone_name)
    return get_briefing(team=team, user=user, timezone_name=timezone_name)


def list_candidates(*, team: Team, user: User, timezone_name: str | None) -> contracts.CandidateList:
    """Today's ranked items with their facts and reasons, without the written text."""
    return briefings.list_candidates(team=team, user=user, timezone_name=timezone_name)
