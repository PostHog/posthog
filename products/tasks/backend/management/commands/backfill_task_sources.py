import time
from collections.abc import Iterator
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import connection

from posthog.dataclasses import frozen

NIL_UUID = "00000000-0000-0000-0000-000000000000"
MAX_BATCH_SIZE = 5000

_LOOP_COLUMN_EXISTS_SQL = (
    "SELECT EXISTS ("
    "SELECT 1 FROM information_schema.columns "
    "WHERE table_schema = current_schema() AND table_name = 'posthog_task' AND column_name = 'loop_id'"
    ")"
)

_CANDIDATES_SQL = (
    "SELECT p.id FROM posthog_task p "
    "WHERE p.id > %(after)s::uuid "
    "AND (%(team_id)s::bigint IS NULL OR p.team_id = %(team_id)s::bigint) "
    "AND ("
    "((p.source_kind IS NULL OR p.source_id IS NULL) "
    "AND (p.signal_report_id IS NOT NULL OR p.hog_flow_id IS NOT NULL{loop_present})) "
    "OR (p.idempotency_key IS NULL AND p.origin_key IS NOT NULL)"
    ") "
    "ORDER BY p.id "
    "LIMIT %(batch_size)s"
)

_UPDATE_SQL = (
    "WITH batch AS ({candidates}) "
    "UPDATE posthog_task AS t "
    "SET source_kind = CASE WHEN t.source_kind IS NOT NULL AND t.source_id IS NOT NULL THEN t.source_kind "
    "ELSE COALESCE(CASE "
    "WHEN t.signal_report_id IS NOT NULL THEN 'signal_report' "
    "WHEN t.hog_flow_id IS NOT NULL THEN 'hog_flow'{loop_kind} "
    "END, t.source_kind) END, "
    "source_id = CASE WHEN t.source_kind IS NOT NULL AND t.source_id IS NOT NULL THEN t.source_id "
    "ELSE COALESCE(CASE "
    "WHEN t.signal_report_id IS NOT NULL THEN t.signal_report_id::text "
    "WHEN t.hog_flow_id IS NOT NULL THEN t.hog_flow_id::text{loop_id} "
    "END, t.source_id) END, "
    "idempotency_key = COALESCE(t.idempotency_key, t.origin_key) "
    "FROM batch WHERE t.id = batch.id "
    "RETURNING t.id"
)

_LOOP_PRESENT = " OR p.loop_id IS NOT NULL"
_LOOP_KIND = " WHEN t.loop_id IS NOT NULL THEN 'loop'"
_LOOP_ID = " WHEN t.loop_id IS NOT NULL THEN t.loop_id::text"


@frozen
class BackfillBatch:
    tasks: int
    cursor: str


def _loop_column_exists() -> bool:
    with connection.cursor() as cursor:
        cursor.execute(_LOOP_COLUMN_EXISTS_SQL)
        row = cursor.fetchone()
    return bool(row and row[0])


def _candidates_sql(*, with_loop: bool) -> str:
    return _CANDIDATES_SQL.format(loop_present=_LOOP_PRESENT if with_loop else "")


def _update_sql(*, with_loop: bool) -> str:
    return _UPDATE_SQL.format(
        candidates=_candidates_sql(with_loop=with_loop),
        loop_kind=_LOOP_KIND if with_loop else "",
        loop_id=_LOOP_ID if with_loop else "",
    )


def backfill_task_sources(
    *,
    team_id: int | None = None,
    batch_size: int = 1000,
    after: str | None = None,
    dry_run: bool = False,
    sleep_seconds: float = 0.0,
) -> Iterator[BackfillBatch]:
    with_loop = _loop_column_exists()
    sql = _candidates_sql(with_loop=with_loop) if dry_run else _update_sql(with_loop=with_loop)
    params = {"team_id": team_id, "batch_size": min(max(batch_size, 1), MAX_BATCH_SIZE)}
    cursor_id = after or NIL_UUID
    while True:
        with connection.cursor() as cursor:
            cursor.execute(sql, {**params, "after": cursor_id})
            task_ids = [row[0] for row in cursor.fetchall()]
        if not task_ids:
            return
        cursor_id = str(max(task_ids))
        yield BackfillBatch(tasks=len(task_ids), cursor=cursor_id)
        if sleep_seconds:
            time.sleep(sleep_seconds)


class Command(BaseCommand):
    help = (
        "Fill source_kind, source_id and idempotency_key on tasks created before those columns existed. "
        "Safe to rerun, and resumable with --after."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, metavar="ID", help="Only tasks in this team")
        parser.add_argument("--batch-size", type=int, default=1000)
        parser.add_argument("--after", help="Resume after this task id, as printed by an earlier run")
        parser.add_argument("--sleep-seconds", type=float, default=0.1, help="Pause between batches")
        parser.add_argument("--dry-run", action="store_true", help="Count the tasks without writing")

    def handle(self, *args: Any, **options: Any) -> None:
        verb = "Would fill" if options["dry_run"] else "Filled"
        total = 0
        for batch in backfill_task_sources(
            team_id=options["team_id"],
            batch_size=options["batch_size"],
            after=options["after"],
            dry_run=options["dry_run"],
            sleep_seconds=options["sleep_seconds"],
        ):
            total += batch.tasks
            self.stdout.write(f"{verb} {total} tasks; resume after {batch.cursor}")
        self.stdout.write(f"{verb} {total} tasks in all")
