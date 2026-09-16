import logging
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

from products.reaper_hog.backend.logic.scan import ScanRequest, run_scan


class Command(BaseCommand):
    help = "Scan a repository scope for dead code candidates and record them in the ReaperHog inventory"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--scope", required=True, help="flags, experiments, all, or a path prefix like products/desktop"
        )
        parser.add_argument(
            "--team-id", required=True, type=int, help="Project whose flag and experiment data is the truth"
        )
        parser.add_argument("--repository", default="PostHog/posthog", help="owner/repo the inventory is keyed on")
        parser.add_argument("--repo-path", default=settings.BASE_DIR, help="Checkout to scan (default: this checkout)")

    def handle(self, *args: Any, **options: Any) -> None:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
        request = ScanRequest(
            team_id=options["team_id"],
            repository=options["repository"],
            scope=options["scope"],
            repo_path=Path(options["repo_path"]),
        )
        self.stdout.write(self.style.MIGRATE_HEADING(f"ReaperHog scan: {request.repository} scope {request.scope}"))
        result = run_scan(request)
        self.stdout.write(result.note)
        self.stdout.write(
            self.style.SUCCESS(
                f"Inventory {result.inventory_id}: {result.hit_count} hits, {len(result.drafts)} clusters"
            )
        )
