import re
import logging
from datetime import timedelta

from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from posthog.temporal.common.schedule import a_create_schedule, a_delete_schedule, a_schedule_exists, a_update_schedule

from products.reaperhog.backend.temporal.types import REAP_SCOPE_WORKFLOW, ReapScopeInputs, reap_workflow_id

logger = logging.getLogger(__name__)

WEEKLY_MONDAY_06_UTC = "0 6 * * 1"
SCHEDULE_PREFIX = "reaperhog-"
_SLUG = re.compile(r"[^a-z0-9]+")


def schedule_id_for(scope: str) -> str:
    return f"{SCHEDULE_PREFIX}{_SLUG.sub('-', scope.lower()).strip('-')}-schedule"


def configured_inputs() -> list[ReapScopeInputs]:
    team_id, user_id, repo_path = (
        settings.REAPERHOG_TEAM_ID,
        settings.REAPERHOG_USER_ID,
        settings.REAPERHOG_REPO_PATH,
    )
    if not settings.REAPERHOG_SCOPES or team_id is None or user_id is None or repo_path is None:
        return []
    return [
        ReapScopeInputs(
            team_id=team_id,
            user_id=user_id,
            repository=settings.REAPERHOG_REPOSITORY,
            scope=scope,
            repo_path=repo_path,
        )
        for scope in settings.REAPERHOG_SCOPES
    ]


async def create_reaperhog_schedules(client: Client) -> None:
    inputs = configured_inputs()
    if not inputs:
        logger.info(
            "ReaperHog schedule skipped: REAPERHOG_SCOPES, REAPERHOG_TEAM_ID, REAPERHOG_USER_ID and REAPERHOG_REPO_PATH are not all set"
        )
    await _drop_unconfigured_schedules(client, {scope_inputs.scope for scope_inputs in inputs})
    for scope_inputs in inputs:
        schedule = Schedule(
            action=ScheduleActionStartWorkflow(
                REAP_SCOPE_WORKFLOW,
                scope_inputs,
                id=reap_workflow_id(
                    team_id=scope_inputs.team_id, repository=scope_inputs.repository, scope=scope_inputs.scope
                ),
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                execution_timeout=timedelta(hours=6),
            ),
            spec=ScheduleSpec(cron_expressions=[WEEKLY_MONDAY_06_UTC]),
            policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
        )
        schedule_id = schedule_id_for(scope_inputs.scope)
        if await a_schedule_exists(client, schedule_id):
            await a_update_schedule(client, schedule_id, schedule)
        else:
            await a_create_schedule(client, schedule_id, schedule, trigger_immediately=False)


async def _drop_unconfigured_schedules(client: Client, configured: set[str]) -> None:
    """Delete the schedules for scopes the configuration no longer names.

    Temporal keeps a schedule until it is deleted, so clearing REAPERHOG_SCOPES or dropping one scope
    from it would otherwise leave that scope scanning, verifying and harvesting forever.
    """
    keep = {schedule_id_for(scope) for scope in configured}
    try:
        async for schedule in await client.list_schedules():
            if not schedule.id.startswith(SCHEDULE_PREFIX) or schedule.id in keep:
                continue
            logger.info("Deleting ReaperHog schedule %s: its scope is no longer configured", schedule.id)
            await a_delete_schedule(client, schedule.id)
    except Exception:
        # Best effort: a listing failure must not stop the configured schedules from being set up.
        logger.exception("reaperhog.drop_unconfigured_schedules_failed")
