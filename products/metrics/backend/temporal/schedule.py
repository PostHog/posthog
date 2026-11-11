"""The 5-minute schedule of the dashboard discovery, and the way the API starts one analysis now."""

import asyncio
from datetime import datetime, timedelta

from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    WorkflowExecutionStatus,
)
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.service import RPCError, RPCStatusCode

from posthog.scheduling.jitter import deterministic_offset
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from products.metrics.backend.suggested_dashboards.timeouts import GENERATE_TIMEOUT, SUGGEST_TIMEOUT
from products.metrics.backend.temporal.inputs import (
    DISCOVERY_WORKFLOW_NAME,
    GENERATE_WORKFLOW_NAME,
    SUGGEST_WORKFLOW_NAME,
    DiscoveryInputs,
    GenerateInputs,
    GenerationRequestInputs,
    SuggestInputs,
    generate_workflow_id,
    suggest_workflow_id,
)

SCHEDULE_ID = "metrics-suggested-dashboards-discovery-schedule"
DISCOVERY_WORKFLOW_ID = "metrics-suggested-dashboards-discovery"
INTERVAL = timedelta(minutes=5)
# Covers two attempts of the 10 minute discovery activity, so the workflow still starts the analyses after a
# slow sweep. The schedule skips a run while the previous one is still going.
DISCOVERY_TIMEOUT = timedelta(minutes=25)


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


def start_regeneration(team_id: int, template_id: str, request: GenerationRequestInputs) -> None:
    """Generate an existing template again. A finished run of the same template is replaced, a running one is not."""
    client = sync_connect()
    asyncio.run(
        client.start_workflow(
            GENERATE_WORKFLOW_NAME,
            GenerateInputs(team_id=team_id, request=request, template_id=template_id),
            id=generate_workflow_id(request.key),
            task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
            execution_timeout=GENERATE_TIMEOUT,
            id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        )
    )


def generation_running(key: str, *, started_after: datetime | None = None) -> bool | None:
    """Whether a generate workflow of the template runs, and started after `started_after` when it is set.

    None when Temporal does not answer.
    """
    try:
        client = sync_connect()
        description = asyncio.run(client.get_workflow_handle(generate_workflow_id(key)).describe())
    except RPCError as error:
        return False if error.status == RPCStatusCode.NOT_FOUND else None
    except Exception:
        return None
    if description.status != WorkflowExecutionStatus.RUNNING:
        return False
    return started_after is None or description.start_time >= started_after
