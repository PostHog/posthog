import time
import argparse
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
from django.db.models import QuerySet

import structlog

from posthog.dataclasses import frozen

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow.search_text import build_search_text

logger = structlog.get_logger(__name__)


@frozen
class SearchTextRebuild:
    checked: int
    changed: int


def rebuild_search_text(queryset: QuerySet[HogFlow], *, page_size: int, dry_run: bool) -> SearchTextRebuild:
    queryset = queryset.only("id", "name", "description", "actions", "draft", "search_text").order_by("id")
    checked = 0
    changed = 0
    last_id: UUID | None = None
    while True:
        page = list((queryset if last_id is None else queryset.filter(id__gt=last_id))[:page_size])
        if not page:
            break
        last_id = page[-1].id
        checked += len(page)
        for hog_flow in page:
            search_text = build_search_text(
                name=hog_flow.name, description=hog_flow.description, actions=hog_flow.actions, draft=hog_flow.draft
            )
            if hog_flow.search_text == search_text:
                continue
            if dry_run:
                changed += 1
                continue
            changed += _rebuild_locked(hog_flow.id)
    return SearchTextRebuild(checked=checked, changed=changed)


def _rebuild_locked(hog_flow_id: UUID) -> int:
    """Rebuild one row under a row lock. A concurrent save either commits before this read or waits for this write,
    so the stored text never comes from older content than the row holds."""
    with transaction.atomic():
        hog_flow = (
            HogFlow.objects.select_for_update()
            .only("id", "name", "description", "actions", "draft", "search_text")
            .filter(id=hog_flow_id)
            .first()
        )
        if hog_flow is None:
            return 0
        search_text = build_search_text(
            name=hog_flow.name, description=hog_flow.description, actions=hog_flow.actions, draft=hog_flow.draft
        )
        if hog_flow.search_text == search_text:
            return 0
        # update() skips post_save, so no worker reload fires: search text never changes how a workflow runs.
        return HogFlow.objects.filter(id=hog_flow_id).update(search_text=search_text)


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


class Command(BaseCommand):
    help = (
        "Fill and rebuild HogFlow.search_text from each workflow's name, description and step content. "
        "Safe to rerun: it writes only the rows whose stored text differs. Run it after any bulk write that changes "
        "those fields without save()."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--page-size", type=_positive_int, default=200, help="Workflows to read per page (default: 200)"
        )
        parser.add_argument("--team-id", type=int, help="Only rebuild this team's workflows")
        parser.add_argument("--dry-run", action="store_true", help="Count the rows to write without writing them")

    def handle(self, *args: Any, **options: Any) -> None:
        started = time.monotonic()
        queryset = HogFlow.objects.all()
        if options.get("team_id"):
            queryset = queryset.filter(team_id=options["team_id"])

        result = rebuild_search_text(queryset, page_size=options["page_size"], dry_run=options["dry_run"])

        verb = "to rebuild" if options["dry_run"] else "rebuilt"
        logger.info(
            "hog_flow_search_text_rebuilt",
            checked=result.checked,
            changed=result.changed,
            dry_run=options["dry_run"],
            duration_seconds=round(time.monotonic() - started, 2),
        )
        self.stdout.write(self.style.SUCCESS(f"Done: {result.checked} checked, {result.changed} {verb}"))
