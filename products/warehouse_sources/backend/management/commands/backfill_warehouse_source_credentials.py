"""Copy the connection fields of existing warehouse sources into their credentials rows."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.warehouse_sources.backend.logic.source_credentials_sync import backfill_source_credentials
from products.warehouse_sources.backend.management.commands._credentials_report import print_backfill_counts


class Command(BaseCommand):
    help = (
        "Create or update the credentials row of each non-deleted warehouse source from its stored job_inputs. "
        "Previews by default; pass --execute to write. Safe to repeat. Never prints field values."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--execute", action="store_true", help="Write rows. Without it the command only counts.")
        parser.add_argument("--team-id", type=int, action="append", default=[], help="Only this team. Repeatable.")
        parser.add_argument("--source-type", default=None, help="Only sources of this type, such as Postgres.")
        parser.add_argument("--batch-size", type=int, default=200, help="Sources per batch.")
        parser.add_argument("--limit", type=int, default=None, help="Stop after this many sources.")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be at least 1")
        if options["limit"] is not None and options["limit"] < 0:
            raise CommandError("--limit must be zero or greater")
        execute: bool = options["execute"]

        counts = backfill_source_credentials(
            execute=execute,
            batch_size=options["batch_size"],
            team_ids=options["team_id"],
            source_type=options["source_type"],
            limit=options["limit"],
            on_batch=lambda size: self.stdout.write(f"processed {size} sources"),
        )
        self.stdout.write(self.style.SUCCESS("Executed" if execute else "Dry run: nothing was written"))
        print_backfill_counts(self.stdout, counts)
