from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import OuterRef, Q, Subquery

from posthog.api.tagged_item import set_tags_on_object

from products.tasks.backend.models import (
    PRIOR_RUN_TAGS_STATE_KEY,
    TASK_RUN_TAGS_STATE_KEY,
    Task,
    TaskRun,
    task_tags_from_state,
)


def backfill_task_tags(team_id: int | None = None, dry_run: bool = False) -> int:
    """Copy the tags of each live task's latest run into TaggedItem rows. Returns the count of tagged tasks."""
    runs_with_tags = TaskRun.objects.filter(
        Q(state__has_key=TASK_RUN_TAGS_STATE_KEY) | Q(state__has_key=PRIOR_RUN_TAGS_STATE_KEY)
    )
    tasks = Task.objects.filter(deleted=False)
    if team_id is not None:
        runs_with_tags = runs_with_tags.filter(team_id=team_id)
        tasks = tasks.filter(team_id=team_id)
    latest_run_state = TaskRun.objects.filter(task_id=OuterRef("pk")).order_by("-created_at", "-id").values("state")[:1]
    tasks = tasks.filter(id__in=runs_with_tags.values("task_id")).annotate(latest_run_state=Subquery(latest_run_state))

    tagged = 0
    for task in tasks.iterator(chunk_size=500):
        tags = task_tags_from_state(task.latest_run_state)
        if not tags:
            continue
        if not dry_run:
            set_tags_on_object(tags, task)
        tagged += 1
    return tagged


class Command(BaseCommand):
    help = "Write the tags of each task's latest run as tags on the task, so the shared tag tools can read them."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, metavar="ID", help="Only tasks in this team")
        parser.add_argument("--dry-run", action="store_true", help="Count the tasks without writing tags")

    def handle(self, *args: Any, **options: Any) -> None:
        tagged = backfill_task_tags(team_id=options["team_id"], dry_run=options["dry_run"])
        verb = "Would tag" if options["dry_run"] else "Tagged"
        self.stdout.write(f"{verb} {tagged} tasks")
