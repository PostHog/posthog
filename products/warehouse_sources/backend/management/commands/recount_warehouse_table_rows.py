from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandParser
from django.db.models import QuerySet

import deltalake

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import (
    build_delta_table_uri,
    delta_storage_options,
    live_row_count,
)


def _latest_completed_rows_synced(schema: ExternalDataSchema) -> int | None:
    # The pipeline filter lets idx_extdatajob_latest_run serve the read. Without it the schema index
    # walks and sorts every job of the schema.
    return (
        ExternalDataJob.objects.filter(
            team_id=schema.team_id,
            pipeline_id=schema.source_id,
            status=ExternalDataJob.Status.COMPLETED,
            schema_id=schema.id,
        )
        .order_by("-created_at")
        .values_list("rows_synced", flat=True)
        .first()
    )


def find_recount_candidates(
    schemas: QuerySet[ExternalDataSchema], *, skip_latest_sync_filter: bool
) -> list[tuple[ExternalDataSchema, DataWarehouseTable, int | None]]:
    candidates: list[tuple[ExternalDataSchema, DataWarehouseTable, int | None]] = []
    for schema in schemas.iterator():
        table = schema.table
        if table is None:
            continue
        rows_synced = _latest_completed_rows_synced(schema)
        # A merge can remove duplicate keys, so more loaded rows than stored rows is a candidate
        # rather than proof. The recount decides.
        if skip_latest_sync_filter or (rows_synced is not None and rows_synced > (table.row_count or 0)):
            candidates.append((schema, table, rows_synced))
    return candidates


def count_table_rows(schema: ExternalDataSchema, table: DataWarehouseTable) -> int:
    # The Delta log gives the count without a read of the data files, which can time out on a large
    # table. In cdc_only mode the schema's table is the companion, which is another Delta table.
    if schema.cdc_table_mode != "cdc_only":
        uri = build_delta_table_uri(schema.folder_path(), schema.resolved_s3_folder_name or schema.name)
        storage_options = delta_storage_options()
        if deltalake.DeltaTable.is_deltatable(uri, storage_options=storage_options):
            row_count = live_row_count(deltalake.DeltaTable(uri, storage_options=storage_options))
            if row_count is not None:
                return row_count
    return table.get_count()


class Command(BaseCommand):
    help = (
        "Recount warehouse tables whose stored row count is lower than the rows their latest "
        "completed sync loaded. A sync that ran over several attempts stored the rows of its last "
        "attempt as the table size. The stored count is a display statistic, and the synced data is "
        "not affected. CDC companion tables that are not the schema's own table are not recounted."
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
            type=UUID,
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

        candidates = find_recount_candidates(schemas, skip_latest_sync_filter=bool(schema_ids))

        if not candidates:
            self.stdout.write(self.style.WARNING("No tables found with a row count below their latest sync."))
            return

        self.stdout.write(f"Found {len(candidates)} table(s) to recount:\n")
        for schema, table, rows_synced in candidates:
            self.stdout.write(
                f"  schema={schema.id} team={schema.team_id} name={schema.name} sync_type={schema.sync_type} "
                f"table={table.id} stored_row_count={table.row_count} "
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
        for schema, table, _rows_synced in candidates:
            try:
                row_count = count_table_rows(schema, table)
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
