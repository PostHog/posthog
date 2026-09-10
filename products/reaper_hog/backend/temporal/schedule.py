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

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from products.reaper_hog.backend.temporal.types import REAP_SCOPE_WORKFLOW, ReapScopeInputs, reap_workflow_id

logger = logging.getLogger(__name__)

WEEKLY_MONDAY_06_UTC = "0 6 * * 1"
_SLUG = re.compile(r"[^a-z0-9]+")


def schedule_id_for(scope: str) -> str:
    return f"reaper-hog-{_SLUG.sub('-', scope.lower()).strip('-')}-schedule"


def configured_inputs() -> list[ReapScopeInputs]:
    team_id, user_id, repo_path = (
        settings.REAPER_HOG_TEAM_ID,
        settings.REAPER_HOG_USER_ID,
        settings.REAPER_HOG_REPO_PATH,
    )
    if not settings.REAPER_HOG_SCOPES or team_id is None or user_id is None or repo_path is None:
        return []
    return [
        ReapScopeInputs(
            team_id=team_id,
            user_id=user_id,
            repository=settings.REAPER_HOG_REPOSITORY,
            scope=scope,
            repo_path=repo_path,
        )
        for scope in settings.REAPER_HOG_SCOPES
    ]


async def create_reaper_hog_schedules(client: Client) -> None:
    inputs = configured_inputs()
    if not inputs:
        logger.info(
            "ReaperHog schedule skipped: REAPER_HOG_SCOPES, REAPER_HOG_TEAM_ID, REAPER_HOG_USER_ID and REAPER_HOG_REPO_PATH are not all set"
        )
        return
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
