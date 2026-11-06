import time
from collections.abc import Iterator
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandParser

from posthog.dataclasses import frozen

from products.tasks.backend.models import Task
from products.tasks.backend.task_run_sync import (
    BACKFILL_ACTOR,
    derive_task_status,
    head_branches_from_runs,
    latest_runs,
    pr_urls_from_runs,
)

NIL_UUID = "00000000-0000-0000-0000-000000000000"
MAX_BATCH_SIZE = 5000


@frozen
class BackfillBatch:
    tasks: int
    cursor: str


def _fill(task_ids: list[UUID]) -> int:
    runs = latest_runs(task_ids)
    pr_urls = pr_urls_from_runs(task_ids)
    head_branches = head_branches_from_runs(task_ids)
    filled = 0
    for task_id in task_ids:
        derived = derive_task_status(runs.get(task_id))
        filled += Task.objects.filter(pk=task_id, status__isnull=True).update(
            status=derived.status,
            status_reason=derived.reason,
            status_detail=derived.detail,
            status_changed_by=BACKFILL_ACTOR,
            head_branch=head_branches.get(task_id),
            pr_urls=pr_urls.get(task_id, []),
        )
    return filled


def backfill_task_status(
    *,
    team_id: int | None = None,
    batch_size: int = 1000,
    after: str | None = None,
    dry_run: bool = False,
    sleep_seconds: float = 0.0,
) -> Iterator[BackfillBatch]:
    limit = min(max(batch_size, 1), MAX_BATCH_SIZE)
    cursor_id = after or NIL_UUID
    while True:
        tasks = Task.objects.filter(id__gt=cursor_id, status__isnull=True)
        if team_id is not None:
            tasks = tasks.filter(team_id=team_id)
        task_ids = list(tasks.order_by("id").values_list("id", flat=True)[:limit])
        if not task_ids:
            return
        cursor_id = str(task_ids[-1])
        yield BackfillBatch(tasks=len(task_ids) if dry_run else _fill(task_ids), cursor=cursor_id)
        if sleep_seconds:
            time.sleep(sleep_seconds)


class Command(BaseCommand):
    help = (
        "Fill status, head_branch and pr_urls on tasks created before those columns existed, "
        "from each task's runs. Safe to rerun, and resumable with --after."
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
        for batch in backfill_task_status(
            team_id=options["team_id"],
            batch_size=options["batch_size"],
            after=options["after"],
            dry_run=options["dry_run"],
            sleep_seconds=options["sleep_seconds"],
        ):
            total += batch.tasks
            self.stdout.write(f"{verb} {total} tasks; resume after {batch.cursor}")
        self.stdout.write(f"{verb} {total} tasks in all")
