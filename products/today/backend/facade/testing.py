"""Test-support facade for today.

A product tests its highlight sources with the context Today runs them with, without importing Today's internals.
"""

from datetime import date

from posthog.models import Team, User

from ..logic.highlight_types import Context
from .contracts import HighlightContext


def highlight_context(*, team: Team, user: User, today: date, scopes: frozenset[str] | None = None) -> HighlightContext:
    return Context(team, user, today, scopes)
