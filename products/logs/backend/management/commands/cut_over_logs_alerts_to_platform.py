from collections import Counter
from typing import Any

from django.core.management.base import BaseCommand

from products.logs.backend.delivery_path_report import team_delivery_paths
from products.logs.backend.platform_cutover import cut_over_team


class Command(BaseCommand):
    help = "Hand one team's logs alerts to the alerts platform. Safe to run again."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="The team to move.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what a real run would do, and move nothing.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        team_id = options["team_id"]
        paths = team_delivery_paths(team_id)
        for function_id in paths.unbound_functions:
            self.stdout.write(f"function={function_id} unbound")
        for alert in paths.alerts:
            if alert.choice.reason is not None:
                self.stdout.write(f"alert={alert.alert_id} path={alert.choice.path} reason={alert.choice.reason}")
        dry_run = options["dry_run"]
        results = cut_over_team(team_id, dry_run=dry_run)
        for result in results:
            if result.skipped is not None:
                self.stdout.write(f"alert={result.alert_id} skipped={result.skipped}")
        delivery = Counter(str(alert.choice.path) for alert in paths.alerts)
        moved = "would_move" if dry_run else "moved"
        outcomes = Counter(str(result.skipped or moved) for result in results)
        self.stdout.write(f"team={team_id} {dict(outcomes) or 'no alerts'} paths={dict(delivery)}")
