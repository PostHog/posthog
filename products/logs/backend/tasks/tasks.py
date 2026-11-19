"""Celery tasks for logs alerting.

The per-alert cap on non-event rows is enforced inline inside the Temporal
activity so the table stays bounded between cleanup runs. This module only hosts
the cold-path cleanup: pruning errored and state-transition rows older than their
retention window. That's slow-moving data, daily cadence is fine.
"""

from celery import shared_task

from posthog.models.scoping import with_team_scope
from posthog.tasks.utils import CeleryQueue


@shared_task(ignore_result=True, name="products.logs.backend.tasks.logs_alert_events_cleanup_task")
def logs_alert_events_cleanup_task() -> None:
    from products.logs.backend.models import LogsAlertEvent

    LogsAlertEvent.clean_up_old_events()


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    max_retries=5,
    autoretry_for=(Exception,),
    retry_backoff=True,
    soft_time_limit=60,
    time_limit=90,
    name="products.logs.backend.tasks.follow_logs_alert_task",
)
@with_team_scope()
def follow_logs_alert_task(team_id: int, alert_id: str) -> None:
    """Copies a logs alert that was just created or turned back on onto the platform.

    A task rather than a call in the request, so a transient failure retries. Nothing else
    discovers a missing copy before the next backfill run. It reads the alert as it is when it
    runs, so a retry after a later edit copies the edit.
    """
    from products.logs.backend.models import (
        LogsAlertConfiguration,  # noqa: PLC0415 — keeps models off the Celery import path
    )
    from products.logs.backend.platform_alert_backfill import (
        follow_logs_alert,  # noqa: PLC0415 — keeps the platform off the Celery import path
    )

    alert = LogsAlertConfiguration.objects.filter(team_id=team_id, id=alert_id).first()
    if alert is not None:
        follow_logs_alert(alert)
