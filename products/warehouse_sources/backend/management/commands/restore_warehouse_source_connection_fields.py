"""Put the connection fields back in the job_inputs of stripped warehouse sources."""

from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.warehouse_sources.backend.logic.source_credentials_strip import (
    FAILED,
    NO_CREDENTIALS,
    restore_connection_fields,
)
from products.warehouse_sources.backend.management.commands._credentials_report import print_backfill_counts


class Command(BaseCommand):
    help = (
        "Undo the strip for the given sources or teams. The connection fields come from the credentials row, or "
        "from the backup when the row is missing or unreadable (or with --prefer-backup). Sync settings and "
        "runtime state stay as they are now. Previews by default; pass --execute to write. Works only while the "
        "backup exists, if the row is lost. Never prints field values."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="Only count (the default).")
        mode.add_argument("--execute", action="store_true", help="Restore.")
        parser.add_argument("--source-id", type=UUID, action="append", default=[], help="This source. Repeatable.")
        parser.add_argument("--team-id", type=int, action="append", default=[], help="Every source of this team.")
        parser.add_argument(
            "--prefer-backup",
            action="store_true",
            help="Take the connection fields from the backup even when the row is readable.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not options["source_id"] and not options["team_id"]:
            raise CommandError("Give --source-id or --team-id")
        execute: bool = options["execute"]

        counts = restore_connection_fields(
            execute=execute,
            source_ids=options["source_id"],
            team_ids=options["team_id"],
            prefer_backup=options["prefer_backup"],
        )
        self.stdout.write(self.style.SUCCESS("Executed" if execute else "Dry run: nothing was written"))
        print_backfill_counts(self.stdout, counts)
        failed = sum(count for (_, outcome), count in counts.items() if outcome == FAILED)
        unrecoverable = sum(count for (_, outcome), count in counts.items() if outcome == NO_CREDENTIALS)
        if failed or unrecoverable:
            raise CommandError(
                f"{failed} sources failed to restore and {unrecoverable} have neither a readable credentials row "
                "nor a backup. See the logs."
            )
