"""Remove the connection fields from the job_inputs of warehouse sources whose credentials row verifies."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.warehouse_sources.backend.logic.source_credentials_strip import FAILED, STRIPPED, strip_connection_fields
from products.warehouse_sources.backend.management.commands._credentials_report import print_backfill_counts


class Command(BaseCommand):
    help = (
        "Back up the job_inputs of each warehouse source, then keep only its sync settings and runtime state. "
        "A source is stripped only when the read flag is on for its team and its credentials row exists, is "
        "readable and matches job_inputs. Previews by default; pass --execute to write. Safe to repeat. "
        "Never prints field values."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="Only count (the default).")
        mode.add_argument("--execute", action="store_true", help="Back up and strip.")
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

        counts = strip_connection_fields(
            execute=execute,
            batch_size=options["batch_size"],
            team_ids=options["team_id"],
            source_type=options["source_type"],
            limit=options["limit"],
            on_batch=lambda size: self.stdout.write(f"processed {size} sources"),
        )
        self.stdout.write(self.style.SUCCESS("Executed" if execute else "Dry run: nothing was written"))
        print_backfill_counts(self.stdout, counts, None if execute else {STRIPPED: "would_strip"})
        failed = sum(count for (_, outcome), count in counts.items() if outcome == FAILED)
        if failed:
            raise CommandError(f"{failed} sources failed to strip. See the logs.")
