"""Delete the job_inputs backups that the strip wrote, after the backup window."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.warehouse_sources.backend.logic.source_credentials_strip import prune_backups


class Command(BaseCommand):
    help = (
        "Delete warehouse source job_inputs backups older than --older-than-days. Previews by default; pass "
        "--execute to delete. After the delete, a source whose credentials row is lost cannot be restored."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="Only count (the default).")
        mode.add_argument("--execute", action="store_true", help="Delete the backups.")
        parser.add_argument("--older-than-days", type=int, default=30, help="Minimum backup age in days.")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["older_than_days"] < 1:
            raise CommandError("--older-than-days must be at least 1")
        execute: bool = options["execute"]

        result = prune_backups(execute=execute, older_than_days=options["older_than_days"])
        self.stdout.write(self.style.SUCCESS("Executed" if execute else "Dry run: nothing was deleted"))
        self.stdout.write(f"matched={result.matched} deleted={result.deleted}")
