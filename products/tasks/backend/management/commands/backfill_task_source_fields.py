from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Q

from products.tasks.backend.models import Task, task_source_fields

BATCH_SIZE = 1000

PENDING = Q(idempotency_key__isnull=True, origin_key__isnull=False) | Q(
    Q(signal_report_id__isnull=False) | Q(hog_flow_id__isnull=False), source_kind__isnull=True
)


def backfill_task_source_fields(dry_run: bool = False, batch_size: int = BATCH_SIZE) -> int:
    filled = 0
    last_id: UUID | None = None
    while True:
        pending = Task.objects.filter(PENDING).order_by("id")
        if last_id is not None:
            pending = pending.filter(id__gt=last_id)
        batch = list(pending.only("id", "origin_key", "signal_report_id", "hog_flow_id")[:batch_size])
        if not batch:
            return filled
        for task in batch:
            task.idempotency_key = task.origin_key or None
            source = task_source_fields(
                signal_report_id=str(task.signal_report_id) if task.signal_report_id else None,
                hog_flow_id=task.hog_flow_id,
            )
            task.source_kind = source.get("source_kind")
            task.source_id = source.get("source_id")
        if not dry_run:
            Task.objects.bulk_update(batch, ["idempotency_key", "source_kind", "source_id"])
        filled += len(batch)
        last_id = batch[-1].id


class Command(BaseCommand):
    help = "Set the source and idempotency key on tasks created before those columns existed."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Count the tasks without writing")

    def handle(self, *args: Any, **options: Any) -> None:
        filled = backfill_task_source_fields(dry_run=options["dry_run"])
        verb = "Would fill" if options["dry_run"] else "Filled"
        self.stdout.write(f"{verb} {filled} tasks")
