from datetime import timedelta

from django.utils import timezone

from posthog.exceptions_capture import capture_exception

from products.tasks.backend.facade import api as tasks_facade

from ..settings import WriterSettings
from .records import JOIN_STATE_KEY

DAILY_RUN_CAP = 60
OPEN_PULL_REQUEST_CAP = 10


class WriterCapReached(Exception):
    pass


def daily_run_cap_reached(writer: WriterSettings) -> bool:
    recent_task_ids = tasks_facade.owner_origin_recent_task_ids(
        team_id=writer.team_id,
        created_by_id=writer.user_id,
        origin_product=tasks_facade.TaskOriginProduct.KNOWLEDGE_WRITER,
        since=timezone.now() - timedelta(days=1),
        limit=DAILY_RUN_CAP,
    )
    return len(recent_task_ids) >= DAILY_RUN_CAP


def unpublished_writer_runs(writer: WriterSettings) -> int:
    in_flight_task_ids = tasks_facade.owner_origin_open_task_ids(
        team_id=writer.team_id,
        created_by_id=writer.user_id,
        origin_product=tasks_facade.TaskOriginProduct.KNOWLEDGE_WRITER,
    )
    return sum(
        1
        for task_id in in_flight_task_ids
        if tasks_facade.read_task_state_entry(task_id, writer.team_id, JOIN_STATE_KEY) is None
    )


def alert_cap_reached(cap: str, *, team_id: int, dedupe_id: str) -> None:
    capture_exception(
        WriterCapReached(f"knowledge writer {cap} cap reached"),
        additional_properties={"team_id": team_id, "dedupe_id": dedupe_id, "cap": cap},
    )
