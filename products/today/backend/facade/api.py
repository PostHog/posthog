"""Facade for today. The only module other products and the presentation layer import."""

from posthog.models import Team, User

from ..feature_flags import is_enabled_for as is_enabled_for
from ..logic import briefings
from . import contracts
from .contracts import (
    BriefingNotFound as BriefingNotFound,
    BriefingWriteRejected as BriefingWriteRejected,
)


def get_briefing(*, team: Team, user: User, timezone_name: str | None) -> contracts.Briefing:
    """Today's briefing for the person. Starts generating one when there is none yet."""
    briefing = briefings.get_or_start_briefing(team=team, user=user, timezone_name=timezone_name)
    return briefings.to_contract(briefing, team, user)


def refresh_briefing(*, team: Team, user: User, timezone_name: str | None) -> contracts.Briefing:
    """Regenerate the current edition. The ready briefing stays until the new one is written."""
    briefings.refresh_briefing(team=team, user=user, timezone_name=timezone_name)
    return get_briefing(team=team, user=user, timezone_name=timezone_name)


def write_briefing(*, team: Team, user: User, write: contracts.BriefingWrite) -> contracts.Briefing:
    """Store the text and items an agent wrote for one of the person's briefings.

    Raises BriefingNotFound for another person's row, and BriefingWriteRejected with the rules
    the text broke.
    """
    briefing = briefings.store_briefing(team=team, user=user, write=write)
    return briefings.to_contract(briefing, team, user)


def list_candidates(*, team: Team, user: User, timezone_name: str | None) -> contracts.CandidateList:
    """Today's ranked items with their facts and reasons, without the written text."""
    return briefings.list_candidates(team=team, user=user, timezone_name=timezone_name)
