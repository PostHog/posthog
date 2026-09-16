from celery import shared_task

from posthog.models.scoping import with_team_scope
from posthog.scoping_audit import skip_team_scope_audit


@shared_task(ignore_result=True, soft_time_limit=210, time_limit=240, acks_late=True, reject_on_worker_lost=True)
@with_team_scope()
def dispatch_implementation_replacement(team_id: int, decision_id: str) -> None:
    from products.signals.backend.implementation_dispatch import (
        ImplementationDispatcher,  # noqa: PLC0415 - keeps the task/autostart cycle lazy
    )

    ImplementationDispatcher().dispatch(team_id, decision_id)


@shared_task(
    ignore_result=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    soft_time_limit=210,
    time_limit=240,
)
@skip_team_scope_audit
def sweep_implementation_dispatches(after_id: str | None = None, through_id: str | None = None) -> None:
    from products.signals.backend.implementation_dispatch import (
        ImplementationDispatcher,  # noqa: PLC0415 - keeps the task/autostart cycle lazy
    )

    ImplementationDispatcher().enqueue_page(after_id, through_id)
