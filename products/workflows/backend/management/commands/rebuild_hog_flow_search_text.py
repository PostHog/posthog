import time
from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import Q

import structlog

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow.search_text import build_search_text

logger = structlog.get_logger(__name__)


class Command(BaseCommand):
    help = (
        "Fill and rebuild HogFlow.search_text from each workflow's name, description and step content. "
        "Safe to rerun: it writes only the rows whose stored text differs."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--page-size", type=int, default=500, help="Workflows to read per page (default: 500)")
        parser.add_argument("--team-id", type=int, help="Only rebuild this team's workflows")
        parser.add_argument("--dry-run", action="store_true", help="Count the rows to write without writing them")

    def handle(self, *args: Any, **options: Any) -> None:
        started = time.monotonic()
        page_size: int = options["page_size"]
        dry_run: bool = options["dry_run"]

        queryset = HogFlow.objects.only("id", "name", "description", "actions", "draft", "search_text")
        if options.get("team_id"):
            queryset = queryset.filter(team_id=options["team_id"])

        checked = 0
        changed = 0
        last_id = None
        while True:
            page_queryset = queryset.order_by("id")
            if last_id is not None:
                page_queryset = page_queryset.filter(id__gt=last_id)
            page = list(page_queryset[:page_size])
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
                changed += 1
                if dry_run:
                    continue
                # A save between the read above and this write stores text built from newer content. The write is
                # conditional on the text read above, so it never replaces that newer text with an older build.
                # update() skips post_save, so no worker reload fires: search text never changes how a workflow runs.
                current = (
                    Q(search_text__isnull=True) if hog_flow.search_text is None else Q(search_text=hog_flow.search_text)
                )
                HogFlow.objects.filter(current, id=hog_flow.id).update(search_text=search_text)
            self.stdout.write(f"Checked {checked} workflows, {changed} {'to rebuild' if dry_run else 'rebuilt'}")

        logger.info(
            "hog_flow_search_text_rebuilt",
            checked=checked,
            changed=changed,
            dry_run=dry_run,
            duration_seconds=round(time.monotonic() - started, 2),
        )
        self.stdout.write(
            self.style.SUCCESS(f"Done: {checked} checked, {changed} {'to rebuild' if dry_run else 'rebuilt'}")
        )
