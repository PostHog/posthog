from celery import shared_task

from posthog.event_usage import EventSource
from posthog.models.scoping import team_scope
from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.data_suggestions.service import (
    build_caller,
    run_build,
    run_data_suggestions,
    run_event_workflows,
)


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
@skip_team_scope_audit
def generate_data_suggestions(team_id: int, user_id: int, lock_token: str) -> None:
    run_data_suggestions(team_id=team_id, user_id=user_id, lock_token=lock_token)


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
@skip_team_scope_audit
def build_data_suggestion(
    team_id: int, user_id: int, suggestion_id: str, lock_token: str, event_source: str, save: bool = False
) -> None:
    # hog_flow.py imports this package through hog_flow_writes, and the draft check imports hog_flow.py.
    from products.workflows.backend.presentation.views.data_suggestion_drafts import (  # noqa: PLC0415 - circular import
        save_draft,
        validated_draft,
    )

    # A saved draft is checked with the editor's draft rules, so blank settings stay blank for the caller to fill.
    rules = EventSource.WEB if save else EventSource(event_source)
    # Saving writes team-scoped rows, and a worker has no request to set the team.
    with team_scope(team_id):
        run_build(
            team_id=team_id,
            user_id=user_id,
            suggestion_id=suggestion_id,
            caller=build_caller(event_source, save=save, user_id=user_id),
            lock_token=lock_token,
            validate_draft=lambda team, workflow: validated_draft(team, workflow, rules),
            save_draft=save_draft if save else None,
        )


@shared_task(ignore_result=True, queue=CeleryQueue.LONG_RUNNING.value)
@skip_team_scope_audit
def build_event_workflows(team_id: int, user_id: int, events: list[str], lock_token: str) -> None:
    # hog_flow.py imports this package through hog_flow_writes, and the draft check imports hog_flow.py.
    from products.workflows.backend.presentation.views.data_suggestion_drafts import (  # noqa: PLC0415 - circular import
        save_draft,
        validated_draft,
    )

    # The drafts are saved for the team to finish in the editor, so they are checked with the editor's draft rules.
    with team_scope(team_id):
        run_event_workflows(
            team_id=team_id,
            user_id=user_id,
            events=tuple(events),
            lock_token=lock_token,
            validate_draft=lambda team, workflow: validated_draft(team, workflow, EventSource.WEB),
            save_draft=save_draft,
        )
