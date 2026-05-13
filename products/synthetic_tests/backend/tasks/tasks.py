"""
Celery tasks for synthetic_tests.

`run_due_synthetic_tests` is the heartbeat: every minute beat fires it, it claims any
SyntheticTest whose `next_run_at` has elapsed (FOR UPDATE SKIP LOCKED so multiple
workers don't double-fire), runs it, and updates `next_run_at` from the cron schedule.
"""

from datetime import UTC, datetime

from django.db import transaction
from django.utils import timezone

import structlog
from celery import shared_task
from croniter import croniter

from products.synthetic_tests.backend.logic.execution import execute_synthetic_test
from products.synthetic_tests.backend.models import SyntheticTest

logger = structlog.get_logger(__name__)

MAX_BATCH = 50


@shared_task(ignore_result=True, queue="default")
def run_due_synthetic_tests() -> None:
    """Pick up any active synthetic tests whose next_run_at has elapsed and execute them."""
    now = timezone.now()
    with transaction.atomic():
        due_tests = list(
            SyntheticTest.objects.select_for_update(skip_locked=True)
            .filter(status=SyntheticTest.Status.ACTIVE)
            .filter(next_run_at__lte=now)
            .order_by("next_run_at")[:MAX_BATCH]
        )

        # Bump next_run_at first so subsequent ticks don't re-claim while we execute below.
        for test in due_tests:
            test.next_run_at = _compute_next_run_at(test.schedule_cron, now)
            test.save(update_fields=["next_run_at", "updated_at"])

    for test in due_tests:
        try:
            execute_synthetic_test(test)
        except Exception as exc:  # noqa: BLE001
            logger.exception("synthetic_test_execution_failed", test_id=str(test.id), error=str(exc))


def _compute_next_run_at(cron_expression: str, base: datetime) -> datetime:
    """Return the next fire time after `base` for the given cron expression, in UTC."""
    iterator = croniter(cron_expression, base.astimezone(UTC))
    return iterator.get_next(datetime)
