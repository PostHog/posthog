from datetime import timedelta

from django.db import connection
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.tasks.backend.facade import api as tasks_facade

from ..settings import WriterSettings
from .records import JOIN_STATE_KEY, SECTION_STATE_KEY

DAILY_RUN_CAP = 60
OPEN_PULL_REQUEST_CAP = 10


class WriterCapReached(Exception):
    pass


class WriterSectionBusy(Exception):
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


@frozen
class InFlightWriterRuns:
    unpublished_runs: int
    busy_sections: frozenset[str]


def in_flight_writer_runs(writer: WriterSettings) -> InFlightWriterRuns:
    in_flight_task_ids = tasks_facade.owner_origin_open_task_ids(
        team_id=writer.team_id,
        created_by_id=writer.user_id,
        origin_product=tasks_facade.TaskOriginProduct.KNOWLEDGE_WRITER,
    )
    unpublished_runs = 0
    busy_sections: set[str] = set()
    for task_id in in_flight_task_ids:
        if tasks_facade.read_task_state_entry(task_id, writer.team_id, JOIN_STATE_KEY) is None:
            unpublished_runs += 1
        section = tasks_facade.read_task_state_entry(task_id, writer.team_id, SECTION_STATE_KEY)
        if isinstance(section, str) and section:
            busy_sections.add(section)
    return InFlightWriterRuns(unpublished_runs=unpublished_runs, busy_sections=frozenset(busy_sections))


def claim_section(writer: WriterSettings, section: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"knowledge-writer-section:{writer.team_id}:{section}"],
        )
    if section in in_flight_writer_runs(writer).busy_sections:
        raise WriterSectionBusy(section)


def alert_cap_reached(cap: str, *, team_id: int, dedupe_id: str) -> None:
    capture_exception(
        WriterCapReached(f"knowledge writer {cap} cap reached"),
        additional_properties={"team_id": team_id, "dedupe_id": dedupe_id, "cap": cap},
    )
