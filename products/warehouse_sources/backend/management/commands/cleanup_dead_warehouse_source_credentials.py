from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.warehouse_sources.backend.logic.source_credentials_cleanup import FAILED, cleanup_dead_credentials
from products.warehouse_sources.backend.management.commands._credentials_report import print_backfill_counts


class Command(BaseCommand):
    help = (
        "Back up and clear dead credentials from idle warehouse sources. "
        "Preview makes no network calls and writes nothing. Pass --execute to check legacy tokens and clean sources. "
        "Output contains counts only."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="Only count (the default).")
        mode.add_argument("--execute", action="store_true", help="Back up and clear dead credentials.")
        parser.add_argument("--team-id", type=int, action="append", default=[], help="Only this team. Repeatable.")
        parser.add_argument("--source-type", default=None, help="Only sources of this type, such as Hubspot.")
        parser.add_argument("--batch-size", type=int, default=200, help="Sources per batch.")
        parser.add_argument("--limit", type=int, default=None, help="Stop after this many sources.")
        parser.add_argument(
            "--idle-days", type=int, default=30, help="Minimum days since an enabled schema last synced."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be at least 1")
        if options["limit"] is not None and options["limit"] < 0:
            raise CommandError("--limit must be zero or greater")
        if options["idle_days"] < 1:
            raise CommandError("--idle-days must be at least 1")
        execute: bool = options["execute"]
        counts = cleanup_dead_credentials(
            execute=execute,
            batch_size=options["batch_size"],
            team_ids=options["team_id"],
            source_type=options["source_type"],
            limit=options["limit"],
            idle_days=options["idle_days"],
            on_batch=lambda size: self.stdout.write(f"processed {size} sources"),
        )
        self.stdout.write(self.style.SUCCESS("Executed" if execute else "Dry run: nothing was written"))
        print_backfill_counts(self.stdout, counts)
        failed = sum(count for (_, outcome), count in counts.items() if outcome == FAILED)
        if failed:
            raise CommandError(f"{failed} sources failed to clean")
