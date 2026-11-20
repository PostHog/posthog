from datetime import timedelta
from uuid import UUID

from django.utils import timezone

import structlog

from posthog.exceptions_capture import capture_exception

from products.tasks.backend.facade import api as tasks_facade

from ..settings import WriterSettings
from .records import PULL_REQUEST_FAILURE_STATE_KEY, PULL_REQUEST_STATE_KEY

logger = structlog.get_logger(__name__)

DAILY_RUN_CAP = 60
OPEN_PULL_REQUEST_CAP = 10


class WriterCapReached(Exception):
    pass


def daily_run_cap_reached(writer: WriterSettings) -> bool:
    recent_run_ids = tasks_facade.owner_origin_recent_run_ids(
        team_id=writer.team_id,
        created_by_id=writer.user_id,
        origin_product=tasks_facade.TaskOriginProduct.KNOWLEDGE_WRITER,
        since=timezone.now() - timedelta(days=1),
        limit=DAILY_RUN_CAP,
    )
    return len(recent_run_ids) >= DAILY_RUN_CAP


def in_flight_writer_run_count(writer: WriterSettings) -> int:
    running_task_ids = tasks_facade.owner_origin_open_task_ids(
        team_id=writer.team_id,
        created_by_id=writer.user_id,
        origin_product=tasks_facade.TaskOriginProduct.KNOWLEDGE_WRITER,
    )
    return len(running_task_ids | publishing_task_ids(writer))


def publishing_task_ids(writer: WriterSettings) -> set[UUID]:
    recent_task_ids = tasks_facade.owner_origin_recent_task_ids(
        team_id=writer.team_id,
        created_by_id=writer.user_id,
        origin_product=tasks_facade.TaskOriginProduct.KNOWLEDGE_WRITER,
        since=timezone.now() - timedelta(days=1),
        limit=DAILY_RUN_CAP,
    )
    completed_task_ids = {
        latest_run.task_id
        for latest_run in tasks_facade.get_latest_run_by_task(recent_task_ids).values()
        if latest_run.status == tasks_facade.TaskRunStatus.COMPLETED
    }
    if not completed_task_ids:
        return set()
    return completed_task_ids - settled_task_ids(writer)


def settled_task_ids(writer: WriterSettings) -> set[UUID]:
    return {
        task_id
        for key in (PULL_REQUEST_STATE_KEY, PULL_REQUEST_FAILURE_STATE_KEY)
        for task_id in tasks_facade.owner_origin_task_ids_with_state_entry(
            team_id=writer.team_id,
            created_by_id=writer.user_id,
            origin_product=tasks_facade.TaskOriginProduct.KNOWLEDGE_WRITER,
            key=key,
        )
    }


def alert_cap_reached(cap: str, *, team_id: int, dedupe_id: str) -> None:
    logger.warning("knowledge_writer_cap_reached", cap=cap, team_id=team_id, dedupe_id=dedupe_id)
    capture_exception(
        WriterCapReached(f"knowledge writer {cap} cap reached"),
        additional_properties={"team_id": team_id, "dedupe_id": dedupe_id, "cap": cap},
    )
