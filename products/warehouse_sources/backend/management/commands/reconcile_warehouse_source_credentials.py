"""Delete credentials rows that no live warehouse source owns, and verify that sources are backfilled."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.warehouse_sources.backend.logic.source_credentials_sync import (
    CREATED,
    SKIPPED_UNKNOWN_TYPE,
    SKIPPED_UNREADABLE,
    UPDATED,
    backfill_source_credentials,
    reconcile_orphan_credentials,
)
from products.warehouse_sources.backend.management.commands._credentials_report import print_backfill_counts

VERIFY_LABELS = {CREATED: "missing_row", UPDATED: "differs_or_unreadable_row"}


class Command(BaseCommand):
    help = (
        "Find credentials rows whose source is missing or soft-deleted. Previews by default; pass --execute to "
        "delete them. With --verify, also report sources whose row is missing or differs, and fail when any exist. "
        "--verify never writes."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--execute", action="store_true", help="Delete orphan rows. Without it the command only counts."
        )
        parser.add_argument("--verify", action="store_true", help="Report sources that are not fully backfilled.")
        parser.add_argument(
            "--team-id", type=int, action="append", default=[], help="With --verify: only this team. Repeatable."
        )
        parser.add_argument("--source-type", default=None, help="With --verify: only sources of this type.")
        parser.add_argument("--batch-size", type=int, default=500, help="Rows or sources per batch.")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be at least 1")
        if options["verify"] and options["execute"]:
            raise CommandError("--verify does not write. Run --execute without it to delete orphans.")
        if not options["verify"] and (options["team_id"] or options["source_type"]):
            raise CommandError("--team-id and --source-type only apply with --verify")

        if options["verify"]:
            self._verify(options)
            return

        result = reconcile_orphan_credentials(execute=options["execute"], batch_size=options["batch_size"])
        self.stdout.write(self.style.SUCCESS("Executed" if options["execute"] else "Dry run: nothing was deleted"))
        self.stdout.write(f"scanned={result.scanned} orphans={result.orphans} deleted={result.deleted}")

    def _verify(self, options: dict[str, Any]) -> None:
        orphans = reconcile_orphan_credentials(execute=False, batch_size=options["batch_size"])
        self.stdout.write(f"orphan rows (not fixed by --verify): {orphans.orphans} of {orphans.scanned}")
        counts = backfill_source_credentials(
            execute=False,
            batch_size=options["batch_size"],
            team_ids=options["team_id"],
            source_type=options["source_type"],
        )
        print_backfill_counts(self.stdout, counts, VERIFY_LABELS)
        not_clean = sum(
            count
            for (_, outcome), count in counts.items()
            if outcome in (CREATED, UPDATED, SKIPPED_UNREADABLE, SKIPPED_UNKNOWN_TYPE)
        )
        if not_clean:
            raise CommandError(
                f"{not_clean} sources are not backfilled. Run backfill_warehouse_source_credentials --execute."
            )
        self.stdout.write(self.style.SUCCESS("Verified: every source has a matching row"))
