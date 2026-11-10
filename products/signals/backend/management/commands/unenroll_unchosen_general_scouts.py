from argparse import ArgumentParser
from collections import Counter
from typing import cast

from django.core.management.base import BaseCommand

from products.signals.backend.scout_harness.config_registry import unenroll_unchosen_general_scouts


class Command(BaseCommand):
    help = (
        "Switch off general scouts that opening the inbox seeded on and no person chose: no one "
        "created or enabled the row, and the team never completed self-driving setup. A team that "
        "edited the general scout is left alone. Dry run unless --apply is passed. Safe to rerun: "
        "a switched-off row no longer matches."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="Print what would change. The default.")
        mode.add_argument("--apply", action="store_true", help="Switch off the selected scouts.")
        parser.add_argument("--team-ids", type=int, nargs="+", help="Limit the run to these projects.")
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--show-team-ids", type=int, default=50, help="How many team ids to print.")

    def handle(self, *args: object, **options: object) -> None:
        apply = bool(options["apply"])
        self.stdout.write("Mode: apply" if apply else "Mode: dry run (pass --apply to write)")
        summary = unenroll_unchosen_general_scouts(
            apply=apply,
            team_ids=cast(list[int] | None, options["team_ids"]),
            batch_size=max(1, min(cast(int, options["batch_size"]), 5000)),
            on_batch=lambda scanned: self.stdout.write(f"Scanned {scanned} rows"),
        )
        self._write_totals("Matched", summary.matched)
        self._write_totals("Skipped, setup completed", summary.skipped_setup_completed)
        self._write_totals("Skipped, team chose other scouts", summary.skipped_team_chose_scouts)
        self._write_totals("Skipped, a person changed the row", summary.skipped_person_touched)
        self._write_totals("Skipped, skill not canonical", summary.skipped_not_canonical)
        if apply:
            self._write_totals("Changed", summary.changed)
            self._write_totals("Not changed, row moved", summary.not_changed)
        else:
            shown = summary.team_ids[: cast(int, options["show_team_ids"])]
            self.stdout.write(f"Teams: {len(summary.team_ids)}. First team ids: {shown}")

    def _write_totals(self, label: str, counts: Counter[tuple[str, str]]) -> None:
        split = ", ".join(f"{managed_by}/{status} {count}" for (managed_by, status), count in sorted(counts.items()))
        self.stdout.write(f"{label}: {counts.total()}" + (f" ({split})" if split else ""))
