"""Report warehouse source references that point at no row, and verify that sources are backfilled."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.warehouse_sources.backend.logic.source_credentials_sync import (
    CREATED,
    NOT_BACKFILLED,
    RECREATED,
    UPDATED,
    backfill_source_credentials,
    reconcile_credential_references,
)
from products.warehouse_sources.backend.management.commands._credentials_report import print_backfill_counts

VERIFY_LABELS = {CREATED: "missing_reference", RECREATED: "missing_row", UPDATED: "differs_or_unreadable_row"}


class Command(BaseCommand):
    help = (
        "List each reference in the inputs of non-deleted warehouse sources that points at no row. With "
        "--verify, also report sources whose row is missing or differs from job_inputs, and fail when any source "
        "is not clean. Never writes and never deletes a row. Never prints field values."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--verify", action="store_true", help="Also report sources that are not backfilled.")
        parser.add_argument("--team-id", type=int, action="append", default=[], help="Only this team. Repeatable.")
        parser.add_argument("--source-type", default=None, help="Only sources of this type, such as Postgres.")
        parser.add_argument("--batch-size", type=int, default=500, help="Sources per batch.")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be at least 1")

        result = reconcile_credential_references(
            batch_size=options["batch_size"], team_ids=options["team_id"], source_type=options["source_type"]
        )
        for ref in result.dangling:
            self.stdout.write(
                f"dangling: team={ref.team_id} source={ref.source_id} type={ref.source_type} "
                f"key={ref.key} integration={ref.integration_id}"
            )
        self.stdout.write(f"scanned={result.scanned} references={result.references} dangling={len(result.dangling)}")
        if not options["verify"]:
            return

        counts = backfill_source_credentials(
            execute=False,
            batch_size=options["batch_size"],
            team_ids=options["team_id"],
            source_type=options["source_type"],
        )
        print_backfill_counts(self.stdout, counts, VERIFY_LABELS)
        not_clean = sum(count for (_, outcome), count in counts.items() if outcome in NOT_BACKFILLED)
        if not_clean or result.dangling:
            raise CommandError(
                f"{not_clean} sources are not backfilled and {len(result.dangling)} references point at no row. "
                "Run backfill_warehouse_source_credentials --execute, then check the dangling references."
            )
        self.stdout.write(self.style.SUCCESS("Verified: every source has a matching row"))
