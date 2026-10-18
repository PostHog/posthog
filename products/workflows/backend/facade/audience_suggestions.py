"""Broadcast audiences written by AI from a project's own events."""

from posthog.models import Team, User

from products.workflows.backend.facade.contracts import AudienceSuggestionsResult
from products.workflows.backend.services.audience_suggestions import service
from products.workflows.backend.services.audience_suggestions.service import (
    FEATURE_FLAG_KEY,
    get_audience_suggestion,
    get_audience_suggestions,
    is_enabled,
    needs_new_generation,
)
from products.workflows.backend.tasks.audience_suggestions import generate_audience_suggestions

__all__ = [
    "FEATURE_FLAG_KEY",
    "get_audience_suggestion",
    "get_audience_suggestions",
    "is_enabled",
    "needs_new_generation",
    "start_audience_suggestions",
]


def start_audience_suggestions(*, team: Team, user: User, refresh: bool) -> AudienceSuggestionsResult:
    return service.start_audience_suggestions(
        team=team,
        refresh=refresh,
        enqueue=lambda lock_token: generate_audience_suggestions.delay(team.id, user.id, lock_token),
    )
