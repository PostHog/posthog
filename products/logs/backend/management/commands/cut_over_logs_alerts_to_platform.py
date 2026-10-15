from collections import Counter
from typing import Any

from django.core.management.base import BaseCommand

from products.logs.backend.platform_cutover import cut_over_team


class Command(BaseCommand):
    help = "Hand one team's logs alerts to the alerts platform. Safe to run again."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="The team to move.")

    def handle(self, *args: Any, **options: Any) -> None:
        results = cut_over_team(options["team_id"])
        for result in results:
            if result.skipped is not None:
                self.stdout.write(f"alert={result.alert_id} skipped={result.skipped}")
        outcomes = Counter(str(result.skipped or "moved") for result in results)
        self.stdout.write(f"team={options['team_id']} {dict(outcomes) or 'no alerts'}")
