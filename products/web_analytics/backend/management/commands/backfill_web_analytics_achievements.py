from typing import cast

from django.core.management.base import BaseCommand, CommandParser

from products.web_analytics.backend.achievements.backfill import backfill_team


class Command(BaseCommand):
    help = (
        "Seed cumulative Web analytics achievement progress for a team from historical data. "
        "Does not queue celebrations and does not backfill streaks. Run manually by ops."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="Team ID to backfill.")

    def handle(self, *args: object, **options: object) -> None:
        team_id = cast(int, options["team_id"])
        touched = backfill_team(team_id)
        self.stdout.write(self.style.SUCCESS(f"Backfilled {touched} achievement progress row(s) for team {team_id}."))
