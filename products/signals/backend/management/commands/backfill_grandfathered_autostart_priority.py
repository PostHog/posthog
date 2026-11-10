from argparse import ArgumentParser
from typing import cast

from django.core.management.base import BaseCommand

from products.signals.backend.autostart_priority_backfill import (
    GRANDFATHERED_AUTOSTART_PRIORITY,
    backfill_grandfathered_autostart_priority,
)


class Command(BaseCommand):
    help = (
        "Set the project pull request threshold to P2 for projects that have automatic pull requests on, "
        "never chose a threshold, and belong to an organization on the grandfathered self-driving plan. "
        "An organization is skipped when the pricing flag gives no confirmed answer. "
        "Dry run unless --apply is passed. Safe to rerun: an updated row no longer matches."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="Print what would change. The default.")
        mode.add_argument("--apply", action="store_true", help="Write the new threshold.")
        parser.add_argument("--team-id", type=int, help="Limit the run to one project.")
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--show-team-ids", type=int, default=20, help="How many team ids to print.")

    def handle(self, *args: object, **options: object) -> None:
        apply = bool(options["apply"])
        summary = backfill_grandfathered_autostart_priority(
            apply=apply,
            team_id=cast(int | None, options["team_id"]),
            batch_size=max(1, min(cast(int, options["batch_size"]), 5000)),
        )
        self.stdout.write("Mode: apply" if apply else "Mode: dry run (pass --apply to write)")
        self.stdout.write(f"Target threshold: {GRANDFATHERED_AUTOSTART_PRIORITY}")
        for outcome, count in sorted(summary.outcomes.items()):
            self.stdout.write(f"{outcome}: {count}")
        shown = summary.team_ids[: cast(int, options["show_team_ids"])]
        self.stdout.write(f"Grandfathered teams selected: {len(summary.team_ids)}. First team ids: {shown}")
