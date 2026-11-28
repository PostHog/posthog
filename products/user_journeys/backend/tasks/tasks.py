"""Celery entrypoints for user journeys. Each task reads its arguments and calls logic."""

from uuid import UUID

from django.db import transaction

from celery import shared_task

from posthog.tasks.utils import CeleryQueue

from ..logic import runs
from ..logic.run_executor import RUN_TIME_BUDGET_SECONDS

# The soft limit raises inside the run, which then ends as errored. The hard limit follows it, and
# `runs.RUN_STALE_AFTER` stays past both so the reaper never ends a run a worker still holds.
EXECUTE_RUN_SOFT_TIME_LIMIT_SECONDS = RUN_TIME_BUDGET_SECONDS + 60
EXECUTE_RUN_TIME_LIMIT_SECONDS = EXECUTE_RUN_SOFT_TIME_LIMIT_SECONDS + 30


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.EXPORTS.value,
    soft_time_limit=EXECUTE_RUN_SOFT_TIME_LIMIT_SECONDS,
    time_limit=EXECUTE_RUN_TIME_LIMIT_SECONDS,
)
def execute_journey_run(team_id: int, run_id: str) -> None:
    runs.execute_run(team_id, UUID(run_id), runtime=runs.production_runtime())


def enqueue_journey_run(team_id: int, run_id: UUID) -> None:
    transaction.on_commit(lambda: execute_journey_run.delay(team_id, str(run_id)))
