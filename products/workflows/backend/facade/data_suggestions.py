"""Workflow ideas written by AI from a project's own events, and building one into a draft workflow."""

from posthog.models import Team, User

from products.workflows.backend.facade.contracts import DataSuggestionsResult
from products.workflows.backend.services.data_suggestions import service
from products.workflows.backend.services.data_suggestions.service import (
    build_data_suggestion,
    get_data_suggestions,
    has_cached_data_suggestions,
)
from products.workflows.backend.tasks.data_suggestions import generate_data_suggestions

__all__ = [
    "build_data_suggestion",
    "get_data_suggestions",
    "has_cached_data_suggestions",
    "start_data_suggestions",
]


def start_data_suggestions(*, team: Team, user: User, refresh: bool) -> DataSuggestionsResult:
    return service.start_data_suggestions(
        team=team,
        refresh=refresh,
        enqueue=lambda lock_token: generate_data_suggestions.delay(team.id, user.id, lock_token),
    )
