"""Temporal wiring for metrics recording rules: a schedule that evaluates every team's rules once a minute.

The evaluation itself lives in `products/metrics/backend/recording_rules/evaluation.py`, so it stays a plain
function a test can call without Temporal.
"""

import asyncio
import datetime as dt
import dataclasses
from collections.abc import Callable
from typing import Any

from django.conf import settings

from temporalio import activity, workflow
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.common.utils import close_db_connections

WORKFLOW_NAME = "metrics-recording-rules-evaluate"
SCHEDULE_ID = "metrics-recording-rules-schedule"
WORKFLOW_ID = "metrics-recording-rules-evaluate"
INTERVAL = dt.timedelta(minutes=1)
# Off the top of the minute, where every other schedule fires and the minute's samples are still arriving.
OFFSET = dt.timedelta(seconds=7)
# Each team's rules run one after another inside their own query budget, so the teams run side by side.
MAX_CONCURRENT_TEAMS = 10
# Above `TEAM_QUERY_BUDGET_SECONDS` and the freshness reads, so a team stops starting queries first.
EVALUATE_START_TO_CLOSE = dt.timedelta(seconds=55)
FIND_START_TO_CLOSE = dt.timedelta(seconds=20)
# The schedule skips a tick while a run is still going, so a slow run delays the next minute rather than
# piling up behind it.
EXECUTION_TIMEOUT = dt.timedelta(minutes=5)


@dataclasses.dataclass(frozen=True)
class RecordingRulesInputs:
    pass


@dataclasses.dataclass(frozen=True)
class TeamRecordingRulesInputs:
    team_id: int
    now: str


@activity.defn
@close_db_connections
def find_teams_with_recording_rules_activity(inputs: RecordingRulesInputs) -> list[int]:
    # Imported in the body, because the workflow below makes this module load inside Temporal's sandbox,
    # which refuses a Django model import.
    from products.metrics.backend.recording_rules.evaluation import teams_with_recording_rules  # noqa: PLC0415

    return teams_with_recording_rules()


@activity.defn
@close_db_connections
def evaluate_team_recording_rules_activity(inputs: TeamRecordingRulesInputs) -> int:
    """Sync, so the thread this blocks is a slot Temporal is accounting for."""
    from posthog.clickhouse.query_tagging import Feature, Product, tags_context  # noqa: PLC0415
    from posthog.models.scoping import team_scope  # noqa: PLC0415

    from products.metrics.backend.recording_rules.evaluation import evaluate_team_recording_rules  # noqa: PLC0415

    with (
        team_scope(inputs.team_id),
        tags_context(product=Product.METRICS, feature=Feature.QUERY, team_id=inputs.team_id),
    ):
        return evaluate_team_recording_rules(inputs.team_id, dt.datetime.fromisoformat(inputs.now))


@workflow.defn(name=WORKFLOW_NAME)
class MetricsRecordingRulesWorkflow(PostHogWorkflow):
    """Evaluates the rules of every team that has an enabled one. Returns how many rules wrote."""

    inputs_cls = RecordingRulesInputs

    @workflow.run
    async def run(self, inputs: RecordingRulesInputs) -> int:
        team_ids = await workflow.execute_activity(
            find_teams_with_recording_rules_activity,
            inputs,
            start_to_close_timeout=FIND_START_TO_CLOSE,
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        now = workflow.now().isoformat()
        slots = asyncio.Semaphore(MAX_CONCURRENT_TEAMS)

        async def evaluate(team_id: int) -> int:
            async with slots:
                # One attempt. A rule records the minute it wrote, so the next tick picks up what this one missed.
                return await workflow.execute_activity(
                    evaluate_team_recording_rules_activity,
                    TeamRecordingRulesInputs(team_id=team_id, now=now),
                    start_to_close_timeout=EVALUATE_START_TO_CLOSE,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )

        results = await asyncio.gather(*(evaluate(team_id) for team_id in team_ids), return_exceptions=True)
        for team_id, result in zip(team_ids, results):
            if isinstance(result, BaseException):
                workflow.logger.warning("Recording rules failed for a team", extra={"team_id": team_id})
        return sum(result for result in results if isinstance(result, int))


async def create_metrics_recording_rules_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            RecordingRulesInputs(),
            id=WORKFLOW_ID,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            execution_timeout=EXECUTION_TIMEOUT,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=INTERVAL, offset=OFFSET)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule, keep_paused=True)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)


METRICS_RECORDING_RULES_WORKFLOWS = [MetricsRecordingRulesWorkflow]
METRICS_RECORDING_RULES_ACTIVITIES: list[Callable[..., Any]] = [
    find_teams_with_recording_rules_activity,
    evaluate_team_recording_rules_activity,
]
