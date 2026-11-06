from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.signals.backend.ranking.cache import backfill_report_sort_cache


class Command(BaseCommand):
    help = "Backfill Inbox sort values after all API and worker processes deploy. Keep inbox-sort-cache off until this completes."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--batch-size", type=int, default=500)

    def handle(self, *args: str, **options: Any) -> None:
        if options["batch_size"] < 1:
            raise CommandError("Batch size must be at least 1.")
        updated = backfill_report_sort_cache(team_id=options["team_id"], batch_size=options["batch_size"])
        self.stdout.write(f"Updated {updated} reports.")
