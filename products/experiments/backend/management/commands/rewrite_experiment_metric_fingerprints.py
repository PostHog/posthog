"""Rewrite the stored `fingerprint` of every inline experiment metric to the current calculation key.

Run it once after a deploy that changes the calculation key version, first as a dry run. Without the rewrite, the
first save of each experiment after the deploy changes every fingerprint, and the activity log describes every
metric as changed. `metric_calculation/stored_fingerprints.py` says what it writes.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.experiments.backend.metric_calculation.stored_fingerprints import (
    FingerprintRewriteReport,
    rewrite_stored_fingerprints,
)


class Command(BaseCommand):
    help = "Rewrite stored inline metric fingerprints to the current calculation key. Dry run unless --apply."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--apply", action="store_true", help="Write the new fingerprints.")
        parser.add_argument(
            "--dry-run", action="store_true", help="Only report what would change. This is the default."
        )
        parser.add_argument("--team-id", type=int, action="append", dest="team_ids", help="Only this team. Repeatable.")
        parser.add_argument("--batch-size", type=int, default=500, help="Experiments read per query.")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["apply"] and options["dry_run"]:
            raise CommandError("--apply and --dry-run exclude each other.")
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be at least 1.")
        apply: bool = options["apply"]
        prefix = "" if apply else "[DRY RUN] "

        def progress(report: FingerprintRewriteReport) -> None:
            self.stdout.write(f"{prefix}{self._describe(report, apply)}")

        report = rewrite_stored_fingerprints(
            apply=apply, team_ids=options["team_ids"], batch_size=options["batch_size"], on_batch=progress
        )
        self.stdout.write(f"{prefix}Done. {self._describe(report, apply)}")
        if report.experiments_failed:
            raise CommandError(f"{report.experiments_failed} experiments failed. Run the command again to retry them.")

    @staticmethod
    def _describe(report: FingerprintRewriteReport, apply: bool) -> str:
        verb = "Rewrote" if apply else "Would rewrite"
        return (
            f"Scanned {report.experiments_scanned} experiments. {verb} {report.metrics_to_rewrite} metric "
            f"fingerprints on {report.experiments_to_rewrite} experiments. {report.experiments_failed} failed."
        )
