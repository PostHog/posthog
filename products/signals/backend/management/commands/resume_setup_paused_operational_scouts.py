from argparse import ArgumentParser
from datetime import timedelta
from typing import cast

from django.core.management.base import BaseCommand

from products.signals.backend.scout_harness.config_registry import resume_setup_paused_operational_scouts


class Command(BaseCommand):
    help = (
        "Resume operational scouts (such as inbox validation) that the old self-driving setup flow "
        "switched off over MCP. A pause the activity log attributes to another client, or does not "
        "record, is left alone. Dry run unless --apply is passed. Safe to rerun: a resumed row no "
        "longer matches."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="Print what would change. The default.")
        mode.add_argument("--apply", action="store_true", help="Resume the selected scouts.")
        parser.add_argument("--team-id", type=int, help="Limit the run to one project.")
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument(
            "--max-gap-seconds",
            type=int,
            default=None,
            help="Optional. Longest time between the seed and the pause for the pause to count as the setup flow's.",
        )
        parser.add_argument("--show-team-ids", type=int, default=20, help="How many team ids to print.")

    def handle(self, *args: object, **options: object) -> None:
        apply = bool(options["apply"])
        max_gap_seconds = cast(int | None, options["max_gap_seconds"])
        summary = resume_setup_paused_operational_scouts(
            apply=apply,
            team_id=cast(int | None, options["team_id"]),
            batch_size=max(1, min(cast(int, options["batch_size"]), 5000)),
            max_gap=None if max_gap_seconds is None else timedelta(seconds=max(0, max_gap_seconds)),
        )
        self.stdout.write("Mode: apply" if apply else "Mode: dry run (pass --apply to write)")
        sources = ", ".join(f"{source} {count}" for source, count in sorted(summary.pause_sources.items()))
        self.stdout.write(f"Pause sources: {sources or 'none'}. Only mcp pauses are selected.")
        for skill_name, count in sorted(summary.selected.items()):
            line = f"{skill_name}: selected {count}, withheld {summary.skipped_withheld[skill_name]}"
            if apply:
                line += f", resumed {summary.resumed[skill_name]}, not resumed {summary.not_resumed[skill_name]}"
            self.stdout.write(line)
        shown = summary.team_ids[: cast(int, options["show_team_ids"])]
        self.stdout.write(f"Teams: {len(summary.team_ids)}. First team ids: {shown}")
