"""Celery tasks for logs alerting.

The per-alert cap on non-event rows is enforced inline inside the Temporal
activity so the table stays bounded between cleanup runs. This module only hosts
the cold-path cleanup: pruning errored and state-transition rows older than their
retention window. That's slow-moving data, daily cadence is fine.
"""

from celery import shared_task


@shared_task(ignore_result=True)
def logs_alert_events_cleanup_task() -> None:
    from products.logs.backend.models import LogsAlertEvent

    LogsAlertEvent.clean_up_old_events()
