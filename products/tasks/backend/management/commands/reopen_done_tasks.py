import time
from collections.abc import Iterator
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from products.tasks.backend.management.backfill import MAX_BATCH_SIZE, NIL_UUID
from products.tasks.backend.models import Task
from products.tasks.backend.task_run_sync import DoneMode, done_mode, reopen_done_task


def reopen_done_tasks(
    *,
    profile: str,
    team_id: int | None = None,
    batch_size: int = 500,
    dry_run: bool = False,
    sleep_seconds: float = 0.0,
) -> Iterator[int]:
    limit = min(max(batch_size, 1), MAX_BATCH_SIZE)
    cursor_id = NIL_UUID
    while True:
        tasks = Task.objects.filter(id__gt=cursor_id, profile=profile, status=Task.Status.DONE)
        if team_id is not None:
            tasks = tasks.filter(team_id=team_id)
        batch = list(tasks.order_by("id").values_list("id", "team_id")[:limit])
        if not batch:
            return
        cursor_id = str(batch[-1][0])
        eligible = [task_id for task_id, task_team_id in batch if done_mode(profile, task_team_id) == DoneMode.OFF]
        yield len(eligible) if dry_run else sum(reopen_done_task(task_id) for task_id in eligible)
        if sleep_seconds:
            time.sleep(sleep_seconds)


class Command(BaseCommand):
    help = (
        "Set done tasks of a profile back to the status their latest run derives, once the profile is off "
        "in the tasks-task-done flag. Skips tasks whose profile is not off. Sends no events or notifications. "
        "Safe to rerun."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--profile", required=True, help="Task profile key")
        parser.add_argument("--team-id", type=int, metavar="ID", help="Only tasks in this team")
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--sleep-seconds", type=float, default=0.1, help="Pause between batches")
        parser.add_argument("--dry-run", action="store_true", help="Count the tasks without writing")

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run = options["dry_run"]
        verb = "Would reopen" if dry_run else "Reopened"
        total = 0
        for reopened in reopen_done_tasks(
            profile=options["profile"],
            team_id=options["team_id"],
            batch_size=options["batch_size"],
            dry_run=dry_run,
            sleep_seconds=options["sleep_seconds"],
        ):
            total += reopened
            if not dry_run:
                self.stdout.write(f"{verb} {total} tasks")
        self.stdout.write(f"{verb} {total} tasks in all")
