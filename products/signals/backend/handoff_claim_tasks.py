from celery import shared_task

from posthog.models.scoping import with_team_scope

from products.signals.backend.report_assignments import hand_off_task_claims


@shared_task(ignore_result=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5)
@with_team_scope()
def reconcile_task_handoff_claims(team_id: int, task_id: str, previous_user_id: int) -> None:
    # The handoff has already committed, so a failed transfer must retry here; it reads the current owner, so a
    # retry after a later handoff still lands on the right person.
    hand_off_task_claims(team_id=team_id, task_id=task_id, previous_user_id=previous_user_id)
