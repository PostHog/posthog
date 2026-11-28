"""Test-support facade for today.

A product tests its highlight and work sources with what Today runs them with, without importing Today's internals.
"""

from datetime import date

from posthog.models import Team, User

from ..logic.highlight_types import Context
from ..logic.work_threads import validate_threads
from .contracts import HighlightContext, WorkThread


def highlight_context(
    *,
    team: Team,
    user: User,
    today: date,
    scopes: frozenset[str] | None = None,
    hidden: frozenset[str] = frozenset(),
) -> HighlightContext:
    return Context(team, user, today, scopes, hidden=hidden)


def assert_work_threads_well_formed(threads: list[WorkThread], *, source: str = "under test") -> None:
    """Raises `WorkThreadInvalid` with the check that the endpoint would fail on, such as a repeated step key."""
    validate_threads(source, threads)
