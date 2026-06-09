"""Temporal workflow + schedule for the API deprecation watch loop (milestone 3).

A scheduled per-team run: scan the repo for version pins → research each against the vendor changelog
→ emit a cited signal to the inbox → optionally dispatch mechanical findings to PostHog Code (draft
PRs) / file issues. `dispatch` defaults off, so a bare schedule only surfaces signals in the inbox —
no PRs until explicitly enabled.

The schedule is created on demand (``schedule_api_deprecation_check`` management command), not wired
into the global startup bootstrap, so it can be brought up on dev first without touching prod.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from posthog.models import Team
    from posthog.sync import database_sync_to_async
    from posthog.temporal.common.heartbeat import Heartbeater
    from posthog.temporal.common.scoped import scoped_temporal

    from products.signals.backend.api_deprecation.agent import ApiDeprecationAgent
    from products.signals.backend.api_deprecation.dispatch import dispatch_findings
    from products.signals.backend.api_deprecation.scanner import scan_repo
    from products.signals.backend.custom_agent.base import AIDataProcessingNotApprovedError

if TYPE_CHECKING:
    from temporalio.client import Client

logger = structlog.get_logger(__name__)

# products/signals/backend/temporal/<this> → repo root is four parents up (matches the deployed tree).
_REPO_ROOT = str(Path(__file__).resolve().parents[4])

API_DEPRECATION_WORKFLOW_NAME = "run-api-deprecation-check"
API_DEPRECATION_SCHEDULE_ID_PREFIX = "api-deprecation-check-schedule"


@dataclass
class ApiDeprecationCheckInput:
    team_id: int
    repository: str = "posthog/posthog"
    repo_root: str | None = None
    # Off by default: a scheduled run surfaces signals in the inbox but opens no PRs until enabled.
    dispatch: bool = False
    dispatch_dry_run: bool = True


@dataclass
class ApiDeprecationCheckOutput:
    pins_found: int
    report_ids: list[str] = field(default_factory=list)
    dispatched: list[str] = field(default_factory=list)


@activity.defn
@scoped_temporal()
async def run_api_deprecation_check_activity(inputs: ApiDeprecationCheckInput) -> ApiDeprecationCheckOutput:
    log = logger.bind(team_id=inputs.team_id, repository=inputs.repository)
    async with Heartbeater():
        pins = scan_repo(inputs.repo_root or _REPO_ROOT)
        team = await Team.objects.select_related("organization").aget(pk=inputs.team_id)
        organization = await database_sync_to_async(lambda: team.organization)()
        if not organization.is_ai_data_processing_approved:
            raise AIDataProcessingNotApprovedError(
                f"Organization {organization.id} has not approved AI data processing; "
                f"refusing API deprecation research for team {inputs.team_id}"
            )

        agent = ApiDeprecationAgent(team=team, pins=pins, repository=inputs.repository)
        reports = await agent.start()
        report_ids = [r.report_id for r in reports]

        dispatched: list[str] = []
        if inputs.dispatch and reports:
            outcomes = await database_sync_to_async(dispatch_findings)(
                team_id=inputs.team_id,
                report_id=reports[0].report_id,
                findings=agent.findings,
                repository=inputs.repository,
                dry_run=inputs.dispatch_dry_run,
            )
            dispatched = [f"{o.action.value}:{o.dedup_key}" for o in outcomes]

        log.info("api deprecation check complete", pins=len(pins), reports=len(report_ids), dispatched=len(dispatched))
        return ApiDeprecationCheckOutput(pins_found=len(pins), report_ids=report_ids, dispatched=dispatched)


@workflow.defn(name=API_DEPRECATION_WORKFLOW_NAME)
class ApiDeprecationCheckWorkflow:
    @workflow.run
    async def run(self, inputs: ApiDeprecationCheckInput) -> ApiDeprecationCheckOutput:
        return await workflow.execute_activity(
            run_api_deprecation_check_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=90),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


def schedule_id_for(team_id: int) -> str:
    return f"{API_DEPRECATION_SCHEDULE_ID_PREFIX}-{team_id}"


async def create_api_deprecation_schedule(
    client: Client,
    *,
    team_id: int,
    repository: str = "posthog/posthog",
    every: timedelta = timedelta(days=1),
    dispatch: bool = False,
    dispatch_dry_run: bool = True,
) -> str:
    """Create or update a per-team daily schedule for the deprecation check. Returns the schedule id."""
    from temporalio.client import (  # noqa: PLC0415
        Schedule,
        ScheduleActionStartWorkflow,
        ScheduleIntervalSpec,
        ScheduleOverlapPolicy,
        SchedulePolicy,
        ScheduleSpec,
    )

    from posthog.temporal.common.schedule import (  # noqa: PLC0415
        a_create_schedule,
        a_schedule_exists,
        a_update_schedule,
    )

    schedule_id = schedule_id_for(team_id)
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            API_DEPRECATION_WORKFLOW_NAME,
            asdict(
                ApiDeprecationCheckInput(
                    team_id=team_id, repository=repository, dispatch=dispatch, dispatch_dry_run=dispatch_dry_run
                )
            ),
            id=schedule_id,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=every)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )
    if await a_schedule_exists(client, schedule_id):
        await a_update_schedule(client, schedule_id, schedule)
    else:
        await a_create_schedule(client, schedule_id, schedule, trigger_immediately=False)
    return schedule_id
