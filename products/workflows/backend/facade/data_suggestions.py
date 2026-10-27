"""Workflow ideas written by AI from a project's own events, and building one into a draft workflow."""

from posthog.event_usage import EventSource
from posthog.models import Team, User

from products.workflows.backend.facade.contracts import BuiltSuggestion, DataSuggestionsResult
from products.workflows.backend.services.data_suggestions import service
from products.workflows.backend.services.data_suggestions.premade import waiting_premade_count
from products.workflows.backend.services.data_suggestions.service import (
    build_caller,
    count_waiting_data_suggestions,
    data_suggestions_acting_user,
    email_sender_ready,
    get_data_suggestions,
    get_premade_workflow,
    needs_new_build,
    needs_new_generation,
    prepare_premade_ideas,
    save_premade_draft,
)
from products.workflows.backend.tasks.data_suggestions import build_data_suggestion, generate_data_suggestions

__all__ = [
    "build_caller",
    "count_waiting_data_suggestions",
    "data_suggestions_acting_user",
    "email_sender_ready",
    "get_data_suggestions",
    "get_premade_workflow",
    "needs_new_build",
    "needs_new_generation",
    "prepare_premade_ideas",
    "save_premade_draft",
    "start_build",
    "start_data_suggestions",
    "waiting_premade_count",
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
