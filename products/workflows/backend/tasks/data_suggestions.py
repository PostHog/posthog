from celery import shared_task

from posthog.event_usage import EventSource
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.data_suggestions.service import run_build, run_data_suggestions


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
@skip_team_scope_audit
def generate_data_suggestions(team_id: int, user_id: int, lock_token: str) -> None:
    run_data_suggestions(team_id=team_id, user_id=user_id, lock_token=lock_token)


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
@skip_team_scope_audit
def build_data_suggestion(team_id: int, user_id: int, suggestion_id: str, lock_token: str, event_source: str) -> None:
    # hog_flow.py imports this package through hog_flow_writes, and the draft check imports hog_flow.py.
    from products.workflows.backend.presentation.views.data_suggestion_drafts import (  # noqa: PLC0415 - circular import
        is_valid_draft,
    )

    run_build(
        team_id=team_id,
        user_id=user_id,
        suggestion_id=suggestion_id,
        caller=event_source,
        lock_token=lock_token,
        is_valid_draft=lambda team, workflow: is_valid_draft(team, workflow, EventSource(event_source)),
    )
