from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.table import DataWarehouseTable


def _latest_completed_rows_synced(schema: ExternalDataSchema) -> int | None:
    return (
        ExternalDataJob.objects.filter(
            team_id=schema.team_id, schema_id=schema.id, status=ExternalDataJob.Status.COMPLETED
        )
        .order_by("-created_at")
        .values_list("rows_synced", flat=True)
        .first()
    )


class Command(BaseCommand):
    help = (
        "Recount warehouse tables whose stored row count is lower than the rows their latest "
        "completed sync loaded. A sync that ran over several attempts stored the rows of its last "
        "attempt as the table size. The stored count is a display statistic, and the synced data is "
        "not affected."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Actually recount and store. Without this flag the command only lists matches (dry-run).",
        )
        parser.add_argument(
            "--team-id",
            type=int,
            default=None,
            help="Only consider schemas belonging to this team",
        )
        parser.add_argument(
            "--schema-id",
            action="append",
            default=None,
            help="Target these schema ids explicitly, skipping the latest-sync filter. Repeatable.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        live_run = options["live_run"]
        team_id = options["team_id"]
        schema_ids = options["schema_id"]

        schemas = ExternalDataSchema.objects.select_related("table").filter(
            deleted=False, table__isnull=False, table__deleted=False
        )
        if team_id is not None:
            schemas = schemas.filter(team_id=team_id)
        if schema_ids:
            schemas = schemas.filter(id__in=schema_ids)

        candidates: list[tuple[ExternalDataSchema, int | None]] = []
        for schema in schemas.iterator():
            rows_synced = _latest_completed_rows_synced(schema)
            # A merge can remove duplicate keys, so more loaded rows than stored rows is a candidate
            # rather than proof. The recount decides.
            if schema_ids or (rows_synced is not None and rows_synced > (schema.table.row_count or 0)):
                candidates.append((schema, rows_synced))

        if not candidates:
            self.stdout.write(self.style.WARNING("No tables found with a row count below their latest sync."))
            return

        self.stdout.write(f"Found {len(candidates)} table(s) to recount:\n")
        for schema, rows_synced in candidates:
            self.stdout.write(
                f"  schema={schema.id} team={schema.team_id} name={schema.name} sync_type={schema.sync_type} "
                f"table={schema.table.id} stored_row_count={schema.table.row_count} "
                f"latest_sync_rows={rows_synced}"
            )

        if not live_run:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDry run: {len(candidates)} table(s) would be recounted. Pass --live-run to execute."
                )
            )
            return

        updated = 0
        failed = 0
        for schema, _rows_synced in candidates:
            table = schema.table
            try:
                # Counts the published files, which can time out on a very large table.
                row_count = table.get_count()
            except Exception as e:
                failed += 1
                self.stdout.write(self.style.ERROR(f"  schema={schema.id} table={table.id} count failed: {e}"))
                continue
            # A sync that finished during the count has already stored a newer count.
            changed = DataWarehouseTable.objects.filter(
                id=table.id, team_id=schema.team_id, row_count=table.row_count
            ).update(row_count=row_count)
            updated += changed
            self.stdout.write(
                f"  schema={schema.id} table={table.id} row_count {table.row_count} -> {row_count}"
                + ("" if changed else " [changed by a sync, skipped]")
            )

        self.stdout.write(self.style.SUCCESS(f"\nDone: {updated} updated, {failed} failed."))
