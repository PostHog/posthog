from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import OuterRef, Subquery
from django.db.models.fields.json import KeyTextTransform

from products.tasks.backend.facade.profiles import legacy_profile_key
from products.tasks.backend.models import Task, TaskRun, task_source_fields

BATCH_SIZE = 1000

SIGNAL_REPORT_STAGE_PROFILE_KEYS = {
    "research": "signals.research",
    "repo_selection": "signals.repo_selection",
    "custom_agent": "signals.custom_agent",
}
SIGNAL_REPORT_DEFAULT_PROFILE_KEY = "signals.implementation"
IMPORTED_CONVERSATION_ORIGIN_KEY_PREFIX = "phai-conversation:"


def _profile_key(task: Task) -> str | None:
    if task.origin_product == Task.OriginProduct.SIGNAL_REPORT and task.internal:
        return SIGNAL_REPORT_STAGE_PROFILE_KEYS.get(
            getattr(task, "latest_ai_stage", None) or "", SIGNAL_REPORT_DEFAULT_PROFILE_KEY
        )
    if (
        task.origin_product == Task.OriginProduct.POSTHOG_AI
        and not task.internal
        and (task.origin_key or "").startswith(IMPORTED_CONVERSATION_ORIGIN_KEY_PREFIX)
    ):
        return "posthog_ai.imported"
    return legacy_profile_key(task.origin_product, task.internal)


def backfill_task_profiles(dry_run: bool = False, batch_size: int = BATCH_SIZE) -> int:
    latest_ai_stage = (
        TaskRun.objects.filter(task_id=OuterRef("pk"))
        .order_by("-created_at", "-id")
        .annotate(agent_stage=KeyTextTransform("ai_stage", "state"))
        .values("agent_stage")[:1]
    )
    filled = 0
    last_id: UUID | None = None
    while True:
        pending = Task.objects.filter(profile__isnull=True).order_by("id")
        if last_id is not None:
            pending = pending.filter(id__gt=last_id)
        batch = list(
            pending.annotate(latest_ai_stage=Subquery(latest_ai_stage)).only(
                "id",
                "origin_product",
                "internal",
                "origin_key",
                "signal_report_id",
                "hog_flow_id",
            )[:batch_size]
        )
        if not batch:
            return filled
        for task in batch:
            task.profile = _profile_key(task)
            task.idempotency_key = task.origin_key or None
            source = task_source_fields(
                signal_report_id=str(task.signal_report_id) if task.signal_report_id else None,
                hog_flow_id=task.hog_flow_id,
            )
            task.source_kind = source.get("source_kind")
            task.source_id = source.get("source_id")
        if not dry_run:
            Task.objects.bulk_update(batch, ["profile", "idempotency_key", "source_kind", "source_id"])
        filled += len(batch)
        last_id = batch[-1].id


class Command(BaseCommand):
    help = "Set the task profile, source and idempotency key on tasks created before task profiles existed."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Count the tasks without writing")

    def handle(self, *args: Any, **options: Any) -> None:
        filled = backfill_task_profiles(dry_run=options["dry_run"])
        verb = "Would fill" if options["dry_run"] else "Filled"
        self.stdout.write(f"{verb} {filled} tasks")
