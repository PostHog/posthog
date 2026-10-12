"""
Celery tasks for metrics.

Async entrypoints that call the facade (facade/api.py).
Keep task functions thin - only call facade methods.
"""

from celery import shared_task

from posthog.models.scoping import with_team_scope
from posthog.tasks.utils import CeleryQueue

from products.metrics.backend.facade import api

FINALIZE_SOFT_TIME_LIMIT_SECONDS = 5 * 60
HARD_TIME_LIMIT_GRACE_SECONDS = 60


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.LONG_RUNNING.value,
    soft_time_limit=FINALIZE_SOFT_TIME_LIMIT_SECONDS,
    time_limit=FINALIZE_SOFT_TIME_LIMIT_SECONDS + HARD_TIME_LIMIT_GRACE_SECONDS,
)
@with_team_scope()
def finalize_metrics_dashboard_import(team_id: int, import_id: str) -> None:
    api.finalize_dashboard_import(team_id=team_id, import_id=import_id)
