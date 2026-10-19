"""Celery tasks for research_desk."""

from django.conf import settings

import structlog
from celery import shared_task

from ..facade import api

logger = structlog.get_logger(__name__)


@shared_task(ignore_result=True)
def run_calendar_scout() -> None:
    team_id = settings.RESEARCH_DESK_TEAM_ID
    if team_id is None:
        return
    result = api.run_calendar_scout(team_id)
    logger.info(
        "research_desk_calendar_scout",
        team_id=team_id,
        meetings=result.meetings,
        sessions_created=result.sessions_created,
        sessions_updated=result.sessions_updated,
    )


@shared_task(ignore_result=True)
def run_source_discovery() -> None:
    team_id = settings.RESEARCH_DESK_TEAM_ID
    if team_id is None:
        return
    result = api.run_source_discovery(team_id)
    logger.info("research_desk_source_discovery", team_id=team_id, sources_created=len(result.sources_created))
