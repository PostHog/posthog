import time
from collections.abc import Iterator
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandParser

from products.tasks.backend.management.backfill import (
    MAX_BATCH_SIZE,
    NIL_UUID,
    BackfillBatch,
    add_backfill_arguments,
    backfill_options,
    report_backfill,
)
from products.tasks.backend.models import Task
from products.tasks.backend.task_run_sync import (
    BACKFILL_ACTOR,
    derive_task_status,
    head_branches_from_runs,
    latest_runs,
    pr_urls_from_runs,
)


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
        add_backfill_arguments(parser)

    def handle(self, *args: Any, **options: Any) -> None:
        report_backfill(self.stdout, backfill_task_status(**backfill_options(options)), dry_run=options["dry_run"])
