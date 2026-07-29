"""Validate CDC shadow-buffer files against the legacy sourcebatch lane.

Read-only exit gate for the buffered-ingress flip: while CDC_BUFFER_SHADOW_WRITE
is on, the legacy path stays authoritative and this command reconciles what the
shadow wrote against what legacy dispatched over the same time window.

Checks per CDC schema:
- filename contract: every buffer file parses, start <= end, and ranges are
  non-overlapping in filename-sort order (a shared boundary is legal — a split
  transaction's batches share its commit position).
- row reconciliation: the `{name}_cdc` (scd2_append) lane keeps one row per
  change event, so its sourcebatch row sum must equal the buffer's row sum
  exactly. The consolidated lane dedupes per PK, so it only bounds the buffer
  from below (buffer >= consolidated).

Windows are aligned by timestamp (buffer LastModified vs sourcebatch created_at),
so edge-of-window skew of one micro-batch is possible — treat single-batch-sized
deltas near the window edge as noise and re-run with a wider --since-hours.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

import psycopg
import pyarrow.parquet as pq

from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL

from products.data_warehouse.backend.facade.api import get_s3_client
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc.buffer import (
    get_buffer_prefix,
    parse_buffer_file_name,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BATCH_TABLE,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.common import strip_s3_protocol


class Command(BaseCommand):
    help = "Validate CDC shadow-buffer files against legacy sourcebatch dispatches (read-only)"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--source-id", required=True, help="ExternalDataSource id to validate")
        parser.add_argument("--since-hours", type=int, default=24, help="Comparison window (default 24)")

    def handle(self, *args: Any, **options: Any) -> None:
        source = ExternalDataSource.objects.get(id=options["source_id"])
        cutoff = datetime.now(UTC) - timedelta(hours=options["since_hours"])

        schemas = list(
            ExternalDataSchema.objects.filter(source=source, sync_type=ExternalDataSchema.SyncType.CDC, deleted=False)
        )
        if not schemas:
            raise CommandError(f"Source {source.id} has no CDC schemas")

        legacy_rows = self._fetch_legacy_row_sums(source, cutoff)
        s3 = get_s3_client()
        violations: list[str] = []

        for schema in schemas:
            buffer_rows, file_count, schema_violations = self._scan_buffer(s3, schema, cutoff)
            violations.extend(schema_violations)

            scd2_rows = legacy_rows.get((str(schema.id), "scd2"))
            consolidated_rows = legacy_rows.get((str(schema.id), "consolidated"))

            self.stdout.write(
                f"{schema.name} (mode={schema.cdc_table_mode}, cdc_mode={schema.cdc_mode}): "
                f"buffer={buffer_rows} rows in {file_count} files, "
                f"legacy scd2={scd2_rows}, legacy consolidated={consolidated_rows}"
            )

            # Snapshot-phase schemas defer legacy dispatch (cdc_deferred_runs), so
            # row reconciliation only means something once the schema streams.
            if schema.cdc_mode != "streaming":
                continue

            if scd2_rows is not None and scd2_rows != buffer_rows:
                violations.append(
                    f"{schema.name}: scd2 lane rows ({scd2_rows}) != buffer rows ({buffer_rows}) — exact match expected"
                )
            if consolidated_rows is not None and buffer_rows < consolidated_rows:
                violations.append(
                    f"{schema.name}: buffer rows ({buffer_rows}) < consolidated rows ({consolidated_rows}) — "
                    "shadow is missing data (dedupe can only shrink, never grow, the legacy count)"
                )

        if violations:
            for violation in violations:
                self.stdout.write(self.style.ERROR(f"VIOLATION: {violation}"))
            raise CommandError(f"{len(violations)} violation(s) found")

        self.stdout.write(self.style.SUCCESS("Buffer validation passed"))

    def _scan_buffer(self, s3: Any, schema: ExternalDataSchema, cutoff: datetime) -> tuple[int, int, list[str]]:
        """Return (row_sum, file_count, violations) for one schema's buffer prefix."""
        prefix = strip_s3_protocol(get_buffer_prefix(schema.team_id, str(schema.id)))
        try:
            entries = s3.ls(prefix, detail=True)
        except FileNotFoundError:
            return 0, 0, []

        violations: list[str] = []
        named: list[tuple[str, tuple[int, int, int]]] = []
        for entry in entries:
            if entry.get("type") == "directory":
                continue
            key = entry["Key"]
            file_name = key.rsplit("/", 1)[-1]
            parsed = parse_buffer_file_name(file_name)
            if parsed is None:
                violations.append(f"{schema.name}: foreign file in buffer prefix: {file_name}")
                continue
            modified = entry.get("LastModified")
            if modified is not None and modified < cutoff:
                continue
            named.append((key, parsed))

        # Filename sort must equal WAL order: ranges strictly ordered, overlap
        # only as a shared boundary (split transaction).
        named.sort(key=lambda item: item[0].rsplit("/", 1)[-1])
        row_sum = 0
        prev_end: int | None = None
        for key, (start_seq, end_seq, _file_index) in named:
            if start_seq > end_seq:
                violations.append(f"{schema.name}: inverted range in {key}")
            if prev_end is not None and start_seq < prev_end:
                violations.append(f"{schema.name}: overlapping range in {key} (starts before previous end {prev_end})")
            prev_end = end_seq

            with s3.open(key, "rb") as f:
                row_sum += pq.ParquetFile(f).metadata.num_rows

        return row_sum, len(named), violations

    def _fetch_legacy_row_sums(self, source: ExternalDataSource, cutoff: datetime) -> dict[tuple[str, str], int]:
        """Sum sourcebatch row_count per (schema_id, lane) since cutoff.

        Lane is derived from resource_name: the `_cdc` suffix marks the
        scd2_append companion, anything else is the consolidated write.
        """
        with psycopg.connect(WAREHOUSE_SOURCES_DATABASE_URL) as conn:
            rows = conn.execute(
                f"""
                SELECT schema_id,
                       CASE WHEN resource_name LIKE '%%\\_cdc' THEN 'scd2' ELSE 'consolidated' END AS lane,
                       COALESCE(SUM(row_count), 0)
                FROM {BATCH_TABLE}
                WHERE source_id = %(source_id)s AND created_at >= %(cutoff)s
                GROUP BY schema_id, lane
                """,
                {"source_id": str(source.id), "cutoff": cutoff},
            ).fetchall()

        return {(str(schema_id), lane): int(total) for schema_id, lane, total in rows}
