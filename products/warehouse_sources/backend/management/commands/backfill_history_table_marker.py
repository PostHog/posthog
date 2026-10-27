"""Mark the history tables that never synced after the `history_table` marker existed.

The sync marks a history table each time it writes to it. A table that stopped syncing earlier, such as
one whose schema dropped its history table, stays unmarked, so the catalog shows its capture columns and
the marker-based checks do not see it.
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.cdc.history_table import history_tables


class Command(BaseCommand):
    help = (
        "Set the history_table marker on registered legacy `_cdc` history tables that lack it. "
        "Previews by default; pass --live-run to write."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Only mark tables of this team.")
        parser.add_argument(
            "--live-run", action="store_true", help="Write the marker. Without this the command only reports."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # Only a legacy history table can be unmarked, and every one ends in `_cdc`, so this narrows the
        # sources before each one is resolved exactly.
        candidates = DataWarehouseTable.objects.filter(
            deleted=False, external_data_source__isnull=False, name__endswith="_cdc"
        )
        if options["team_id"] is not None:
            candidates = candidates.filter(team_id=options["team_id"])
        sources = ExternalDataSource.objects.filter(id__in=candidates.values("external_data_source_id"))

        marked = 0
        scanned = 0
        # Streamed, so memory stays flat across every source of the installation.
        for source in sources.iterator(chunk_size=500):
            scanned += 1
            for table in (table for table in history_tables(source) if not table.is_history_table):
                self.stdout.write(f"team={table.team_id} source={source.id} table={table.id} name={table.name}")
                marked += 1
                if options["live_run"]:
                    table.mark_as_history_table()
                    table.save(update_fields=["options"])

        verb = "Marked" if options["live_run"] else "Would mark"
        self.stdout.write(f"{verb} {marked} table(s) across {scanned} candidate source(s).")
