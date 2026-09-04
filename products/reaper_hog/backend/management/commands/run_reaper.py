import logging
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.reaper_hog.backend.logic.constants import MAX_VERIFICATIONS_PER_RUN
from products.reaper_hog.backend.logic.scan import ScanRequest, run_scan
from products.reaper_hog.backend.logic.verification import VerifyRequest, render_verification_summary, run_verification


class Command(BaseCommand):
    help = "Scan a repository scope for dead code candidates, and optionally verify them in a sandbox session"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--scope", required=True, help="flags, experiments, all, or a path prefix like products/desktop"
        )
        parser.add_argument(
            "--team-id", required=True, type=int, help="Project whose flag and experiment data is the truth"
        )
        parser.add_argument("--repository", default="PostHog/posthog", help="owner/repo the inventory is keyed on")
        parser.add_argument("--repo-path", default=settings.BASE_DIR, help="Checkout to scan (default: this checkout)")
        parser.add_argument("--skip-scan", action="store_true", help="Reuse the existing inventory instead of scanning")
        parser.add_argument(
            "--verify", action="store_true", help="Verify candidates in a sandbox session after the scan"
        )
        parser.add_argument("--user-id", type=int, help="User the sandbox session runs as (required with --verify)")
        parser.add_argument("--branch", default="master", help="Branch the sandbox checks out for verification")
        parser.add_argument("--max-clusters", type=int, default=MAX_VERIFICATIONS_PER_RUN, help="Verification budget")

    def handle(self, *args: Any, **options: Any) -> None:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
        if options["verify"] and options["user_id"] is None:
            raise CommandError("--verify needs --user-id")
        if not options["skip_scan"]:
            self._scan(options)
        if options["verify"]:
            self._verify(options)

    def _scan(self, options: dict[str, Any]) -> None:
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

    def _verify(self, options: dict[str, Any]) -> None:
        request = VerifyRequest(
            team_id=options["team_id"],
            user_id=options["user_id"],
            repository=options["repository"],
            scope=options["scope"],
            branch=options["branch"],
            max_clusters=options["max_clusters"],
        )
        self.stdout.write(self.style.MIGRATE_HEADING(f"ReaperHog verify: up to {request.max_clusters} clusters"))
        result = run_verification(request)
        self.stdout.write(self.style.SUCCESS(render_verification_summary(request, result)))
