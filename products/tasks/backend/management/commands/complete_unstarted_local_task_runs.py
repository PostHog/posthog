import time
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import F, QuerySet
from django.utils import timezone

from products.tasks.backend.management.backfill import MAX_BATCH_SIZE, NIL_UUID
from products.tasks.backend.models import TaskRun
from products.tasks.backend.task_run_sync import BACKFILL_ACTOR, sync_task_status

IDLE_FOR = timedelta(hours=24)


def _unstarted_local_runs(team_id: int | None) -> QuerySet[TaskRun]:
    runs = TaskRun.objects.filter(
        status=TaskRun.Status.NOT_STARTED,
        environment=TaskRun.Environment.LOCAL,
        scheduled_at__isnull=True,
        updated_at__lt=timezone.now() - IDLE_FOR,
    )
    return runs if team_id is None else runs.filter(team_id=team_id)


def complete_unstarted_local_task_runs(
    *,
    team_id: int | None = None,
    batch_size: int = 500,
    dry_run: bool = False,
    sleep_seconds: float = 0.0,
) -> Iterator[int]:
    runs = _unstarted_local_runs(team_id)
    if dry_run:
        yield runs.count()
        return
    limit = min(max(batch_size, 1), MAX_BATCH_SIZE)
    cursor_id = NIL_UUID
    while True:
        batch = list(runs.filter(id__gt=cursor_id).order_by("id").values_list("id", "task_id")[:limit])
        if not batch:
            return
        cursor_id = str(batch[-1][0])
        completed = runs.filter(id__in=[run_id for run_id, _ in batch]).update(
            status=TaskRun.Status.COMPLETED, completed_at=F("updated_at")
        )
        for task_id in dict.fromkeys(task_id for _, task_id in batch):
            sync_task_status(task_id, changed_by=BACKFILL_ACTOR)
        yield completed
        if sleep_seconds:
            time.sleep(sleep_seconds)


class Command(BaseCommand):
    help = (
        "Complete local task runs that were left in not_started with no schedule, so their tasks stop "
        "reading as queued. Sends no events or notifications. Safe to rerun."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, metavar="ID", help="Only runs in this team")
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--sleep-seconds", type=float, default=0.1, help="Pause between batches")
        parser.add_argument("--dry-run", action="store_true", help="Count the runs without writing")

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run = options["dry_run"]
        verb = "Would complete" if dry_run else "Completed"
        total = 0
        for completed in complete_unstarted_local_task_runs(
            team_id=options["team_id"],
            batch_size=options["batch_size"],
            dry_run=dry_run,
            sleep_seconds=options["sleep_seconds"],
        ):
            total += completed
            if not dry_run:
                self.stdout.write(f"{verb} {total} runs")
        self.stdout.write(f"{verb} {total} runs in all")
