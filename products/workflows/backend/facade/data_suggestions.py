"""Workflow ideas written by AI from a project's own events, and building one into a draft workflow."""

from posthog.event_usage import EventSource
from posthog.models import Team, User

from products.workflows.backend.facade.contracts import BuiltSuggestion, DataSuggestionsResult
from products.workflows.backend.services.data_suggestions import service
from products.workflows.backend.services.data_suggestions.service import (
    FEATURE_FLAG_KEY,
    build_caller,
    count_waiting_data_suggestions,
    data_suggestions_acting_user,
    email_sender_ready,
    get_data_suggestions,
    is_data_suggestions_enabled,
    needs_new_build,
    needs_new_generation,
)
from products.workflows.backend.tasks.data_suggestions import build_data_suggestion, generate_data_suggestions

__all__ = [
    "FEATURE_FLAG_KEY",
    "build_caller",
    "count_waiting_data_suggestions",
    "data_suggestions_acting_user",
    "email_sender_ready",
    "get_data_suggestions",
    "is_data_suggestions_enabled",
    "needs_new_build",
    "needs_new_generation",
    "prepare_data_suggestions",
    "start_build",
    "start_data_suggestions",
]


def start_data_suggestions(*, team: Team, user: User, refresh: bool) -> DataSuggestionsResult:
    return service.start_data_suggestions(
        team=team,
        refresh=refresh,
        enqueue=lambda lock_token: generate_data_suggestions.delay(team.id, user.id, lock_token),
    )


def start_build(
    *, team: Team, user: User, suggestion_id: str, retry: bool, save: bool, event_source: EventSource
) -> BuiltSuggestion:
    return service.start_build(
        team=team,
        suggestion_id=suggestion_id,
        caller=build_caller(event_source.value, save=save, user_id=user.id),
        retry=retry,
        enqueue=lambda lock_token: build_data_suggestion.delay(
            team.id, user.id, suggestion_id, lock_token, event_source.value, save
        ),
    )


def prepare_data_suggestions(*, team: Team, user: User, refresh: bool) -> DataSuggestionsResult:
    """Generates the cards and builds each one in this process, so the ideas wait for a team that has not opened
    the workflows page yet. A click then creates the stored workflow without a model call."""
    service.start_data_suggestions(
        team=team,
        refresh=refresh,
        enqueue=lambda lock_token: service.run_data_suggestions(
            team_id=team.id, user_id=user.id, lock_token=lock_token
        ),
    )
    service.prebuild_suggestions(
        team_id=team.id,
        user_id=user.id,
        enqueue=lambda suggestion_id, build_token: build_data_suggestion(
            team.id, user.id, suggestion_id, build_token, EventSource.WEB.value
        ),
    )
    return service.get_data_suggestions(team=team)
