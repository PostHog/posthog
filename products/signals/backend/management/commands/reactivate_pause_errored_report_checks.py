from argparse import ArgumentParser
from typing import cast

from django.core.management.base import BaseCommand

from products.signals.backend.report_check_agent import reactivate_checks_errored_by_scout_pause


class Command(BaseCommand):
    help = (
        "Reactivate agent report checks that dispatch retired as errored only because their scout was "
        "paused. Only checks on a resolved report with time left before their horizon match. Dry run "
        "unless --apply is passed. Safe to rerun: a reactivated check no longer matches."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="Print what would change. The default.")
        mode.add_argument("--apply", action="store_true", help="Reactivate the matched checks.")
        parser.add_argument("--team-id", type=int, help="Limit the run to one environment.")
        parser.add_argument("--show-team-ids", type=int, default=20, help="How many team ids to print.")

    def handle(self, *args: object, **options: object) -> None:
        apply = bool(options["apply"])
        summary = reactivate_checks_errored_by_scout_pause(apply=apply, team_id=cast(int | None, options["team_id"]))
        self.stdout.write("Mode: apply" if apply else "Mode: dry run (pass --apply to write)")
        line = f"Matched checks: {summary.matched}"
        if apply:
            line += f", reactivated {summary.reactivated}"
        self.stdout.write(line)
        shown = summary.team_ids[: cast(int, options["show_team_ids"])]
        self.stdout.write(f"Teams: {len(summary.team_ids)}. First team ids: {shown}")
