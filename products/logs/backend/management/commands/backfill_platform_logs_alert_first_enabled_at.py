from typing import Any

from django.core.management.base import BaseCommand

from products.logs.backend.platform_alert_backfill import backfill_copies_first_enabled_at


class Command(BaseCommand):
    help = (
        "Copy each logs alert's first_enabled_at onto its alerts platform copy, where the two differ. "
        "Writes nothing without --apply."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--team-id", type=int, action="append", dest="team_ids", help="Only this team. Repeat for more."
        )
        parser.add_argument("--apply", action="store_true", help="Write the changes. Without it, only count them.")

    def handle(self, *args: Any, **options: Any) -> None:
        dry_run = not options["apply"]
        result = backfill_copies_first_enabled_at(team_ids=options["team_ids"], dry_run=dry_run)
        verb = "Would set" if dry_run else "Set"
        for team_id, count in result.matched.items():
            self.stdout.write(f"Team {team_id}: {verb.lower()} first_enabled_at on {count} copies")
        self.stdout.write(
            f"{verb} first_enabled_at on {sum(result.matched.values())} logs platform copies "
            f"across {len(result.matched)} teams"
        )
        if result.failed_team_ids:
            self.stderr.write(f"Failed for teams: {', '.join(map(str, result.failed_team_ids))}")
