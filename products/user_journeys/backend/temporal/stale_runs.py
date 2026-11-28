"""A schedule that ends journey runs no worker will finish, in every team.

A run is created on a web pod and executed by a Celery worker. When the worker dies, or the task
never leaves the queue, the run stays `pending` or `running` and blocks the next run of its journey.
"""

import dataclasses
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections

import structlog
from temporalio import activity, common, workflow
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from posthog.scheduling.jitter import deterministic_offset
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

with workflow.unsafe.imports_passed_through():
    from products.user_journeys.backend.logic import runs

logger = structlog.get_logger(__name__)

WORKFLOW_NAME = "user-journeys-reap-stale-runs"
SCHEDULE_ID = "user-journeys-reap-stale-runs-schedule"
# Well under `runs.RUN_STALE_AFTER`, so a stuck run blocks its journey for at most one interval longer.
SCHEDULE_INTERVAL = timedelta(minutes=5)


@dataclasses.dataclass(frozen=True)
class ReapStaleRunsInputs:
    pass


@dataclasses.dataclass(frozen=True)
class ReapStaleRunsResult:
    ended: int


@activity.defn
def reap_stale_journey_runs_activity(inputs: ReapStaleRunsInputs) -> ReapStaleRunsResult:
    close_old_connections()
    ended = runs.reap_stale_runs_all_teams()
    if ended:
        logger.info("user_journeys.stale_runs_reaped", ended=ended)
    return ReapStaleRunsResult(ended=ended)


@workflow.defn(name=WORKFLOW_NAME)
class ReapStaleJourneyRunsWorkflow(PostHogWorkflow):
    inputs_cls = ReapStaleRunsInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: ReapStaleRunsInputs) -> ReapStaleRunsResult:
        # One attempt: the next scheduled run reads the same rule, so a retry adds nothing.
        return await workflow.execute_activity(
            reap_stale_journey_runs_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=common.RetryPolicy(maximum_attempts=1),
        )


async def create_reap_stale_journey_runs_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            ReapStaleRunsInputs(),
            id=SCHEDULE_ID,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            intervals=[
                ScheduleIntervalSpec(
                    every=SCHEDULE_INTERVAL, offset=deterministic_offset(SCHEDULE_ID, SCHEDULE_INTERVAL)
                )
            ]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=SCHEDULE_INTERVAL),
    )
    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
