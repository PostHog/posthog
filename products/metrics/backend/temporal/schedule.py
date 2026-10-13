"""The 5-minute schedule of the dashboard discovery, and the way the API starts one analysis now."""

import asyncio
from datetime import timedelta

from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.scheduling.jitter import deterministic_offset
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from products.metrics.backend.temporal.inputs import (
    DISCOVERY_WORKFLOW_NAME,
    SUGGEST_WORKFLOW_NAME,
    DiscoveryInputs,
    SuggestInputs,
    suggest_workflow_id,
)

SCHEDULE_ID = "metrics-suggested-dashboards-discovery-schedule"
DISCOVERY_WORKFLOW_ID = "metrics-suggested-dashboards-discovery"
INTERVAL = timedelta(minutes=5)
DISCOVERY_TIMEOUT = timedelta(minutes=4)
SUGGEST_TIMEOUT = timedelta(minutes=20)


async def create_suggested_dashboards_discovery_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            DISCOVERY_WORKFLOW_NAME,
            DiscoveryInputs(),
            id=DISCOVERY_WORKFLOW_ID,
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            execution_timeout=DISCOVERY_TIMEOUT,
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=INTERVAL, offset=deterministic_offset(SCHEDULE_ID, INTERVAL))]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule, keep_paused=True)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)


def start_team_analysis(team_id: int, *, force: bool) -> None:
    """Start the analysis of one team now. A run that is already going for the team is reused."""
    client = sync_connect()
    asyncio.run(
        client.start_workflow(
            SUGGEST_WORKFLOW_NAME,
            SuggestInputs(team_id=team_id, force=force),
            id=suggest_workflow_id(team_id),
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            execution_timeout=SUGGEST_TIMEOUT,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        )
    )
