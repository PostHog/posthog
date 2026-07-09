"""Wipe all ReviewHog DB state so a re-run starts from a genuinely clean slate.

Postgres is the single source of truth for a review (there is no on-disk store), so this one
command is the entire "clean state" story while iterating: it deletes every `ReviewReportArtefact`
(findings, verdicts, commit snapshots, and the `chunk_set` / `perspective_result` working state the
DB-driven resume reads back), every `ReviewReport`, every
`ReviewSkillConfig` (per-user perspective enablement + validator selection), and every
`ReviewUserSettings` (per-user trigger opt-outs + urgency threshold, which drive what gets reviewed
and what gets published) — across all teams. Wiping the configs and settings resets every user to
the defaults, re-seeded on their next run or read.

Local iteration helper only — refuses to run unless `DEBUG=True`.
"""

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact, ReviewSkillConfig, ReviewUserSettings


class Command(BaseCommand):
    help = (
        "Wipe all ReviewHog DB state (every ReviewReport + ReviewReportArtefact + ReviewSkillConfig "
        "+ ReviewUserSettings, across all teams). DEBUG only."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be deleted without touching the database.",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Skip the interactive confirmation prompt.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("reset_review_hog only runs with DEBUG=True — it wipes every team's ReviewHog rows.")

        dry_run: bool = options["dry_run"]
        skip_confirm: bool = options["yes"]

        # A full local wipe is genuinely cross-team, so go through `unscoped()` — the fail-closed
        # managers would otherwise raise without a team context (CLAUDE.md cross-team escape hatch).
        artefacts = ReviewReportArtefact.objects.unscoped()
        reports = ReviewReport.objects.unscoped()
        configs = ReviewSkillConfig.objects.unscoped()
        user_settings = ReviewUserSettings.objects.unscoped()
        artefact_count = artefacts.count()
        report_count = reports.count()
        config_count = configs.count()
        settings_count = user_settings.count()

        if report_count == 0 and artefact_count == 0 and config_count == 0 and settings_count == 0:
            self.stdout.write("ReviewHog DB is already empty — nothing to delete.")
            return

        summary = (
            f"{report_count} ReviewReport(s), {artefact_count} ReviewReportArtefact(s), "
            f"{config_count} ReviewSkillConfig(s), and {settings_count} ReviewUserSettings"
        )

        if dry_run:
            self.stdout.write(self.style.NOTICE(f"[dry-run] Would delete {summary} across all teams."))
            return

        if not skip_confirm:
            self.stdout.write(self.style.WARNING(f"This will DELETE {summary} across ALL teams."))
            if input("Type 'yes' to confirm: ") != "yes":
                self.stdout.write("Aborted.")
                return

        # Delete artefacts first, then reports. The artefact→report FK is CASCADE, so deleting the
        # reports alone would also drop the artefacts, but the explicit order keeps the tallies true.
        # Skill configs and user settings are independent (no FK to reports), so wipe them too.
        artefacts.delete()
        reports.delete()
        configs.delete()
        user_settings.delete()

        self.stdout.write(self.style.SUCCESS(f"Done. Deleted {summary}."))
