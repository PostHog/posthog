from argparse import ArgumentParser
from typing import cast

from django.core.management.base import BaseCommand

from products.signals.backend.anomaly_scores.source_backfill import backfill_analytics_sources, revert_analytics_sources


class Command(BaseCommand):
    help = (
        "Turn on the Product analytics source for self-driving projects that completed setup before onboarding "
        "enabled it, so anomaly scoring can enroll them. The row is written with alert_scope off, so no alert "
        "becomes a signal. Skips a project that has a row already, or that turned anomaly scoring off. "
        "Dry run unless --apply is passed. Safe to rerun. --revert deletes the rows this command wrote that "
        "nobody changed since."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="Print what would change. The default.")
        mode.add_argument("--apply", action="store_true", help="Write the changes.")
        parser.add_argument("--revert", action="store_true", help="Delete the rows this command wrote.")
        parser.add_argument("--team-ids", type=int, nargs="+", help="Limit the run to these projects.")
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--show-team-ids", type=int, default=50, help="How many team ids to print.")

    def handle(self, *args: object, **options: object) -> None:
        apply = bool(options["apply"])
        team_ids = cast(list[int] | None, options["team_ids"])
        show = cast(int, options["show_team_ids"])
        self.stdout.write("Mode: apply" if apply else "Mode: dry run (pass --apply to write)")
        if options["revert"]:
            reverted = revert_analytics_sources(apply=apply, team_ids=team_ids)
            self.stdout.write(f"Matched: {reverted.matched}")
            self.stdout.write(f"Skipped, row changed since the backfill: {reverted.skipped_changed}")
            if apply:
                self.stdout.write(f"Deleted: {reverted.deleted}")
            self.stdout.write(f"Teams: {len(reverted.team_ids)}. First team ids: {reverted.team_ids[:show]}")
            return
        summary = backfill_analytics_sources(
            apply=apply,
            team_ids=team_ids,
            batch_size=max(1, min(cast(int, options["batch_size"]), 5000)),
            on_batch=lambda scanned: self.stdout.write(f"Scanned {scanned} teams"),
        )
        self.stdout.write(f"Matched: {summary.matched}")
        self.stdout.write(f"In the scoring rollout now: {summary.in_rollout}")
        if apply:
            self.stdout.write(f"Created: {summary.created}")
            self.stdout.write(f"Not created, a row appeared: {summary.not_created}")
        self.stdout.write(f"Teams: {len(summary.team_ids)}. First team ids: {summary.team_ids[:show]}")
