"""Validate CDC shadow-buffer files against the legacy sourcebatch lane.

Read-only exit gate for the buffered-ingress flip: while the dwh-cdc-buffer-shadow
flag is on, the legacy path stays authoritative and this command reconciles what the
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

Known windows where sums legitimately diverge:
- Around the snapshot→streaming flip: shadow writes buffer files during the
  snapshot phase, but their legacy dispatches are deferred and inserted with
  created_at = flip time. Validate with a window that starts after the schema
  began streaming (or spans the entire snapshot phase).
- After a mid-run activity retry: the legacy lane re-inserts the replayed prefix
  of an in-flight transaction (accepted duplicate scd2 rows) while the buffer's
  same-named files overwrite. A `(run_uuid, batch_index)` dispatched more than
  once in the window therefore downgrades the scd2 exact-match to a warning.
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
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import CDC_COMPANION_SUFFIX
from products.warehouse_sources.backend.temporal.data_imports.cdc.buffer import (
    BufferFileSpan,
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

        legacy_rows, retried_batches = self._fetch_legacy_row_sums(source, cutoff)
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

            # A streaming flush dispatches legacy immediately, so buffered rows with
            # no legacy dispatches at all means the legacy lane is stalled — absence
            # must fail, not silently skip the comparison.
            required_lanes = {"consolidated": ["consolidated"], "cdc_only": ["scd2"], "both": ["scd2", "consolidated"]}
            if buffer_rows > 0:
                for lane in required_lanes.get(schema.cdc_table_mode, []):
                    if legacy_rows.get((str(schema.id), lane)) is None:
                        violations.append(
                            f"{schema.name}: buffer has {buffer_rows} rows but no legacy {lane} dispatches "
                            "in the window — legacy lane stalled or producer failing"
                        )

            if scd2_rows is not None and scd2_rows != buffer_rows:
                # Legacy re-inserts replayed rows on activity retry while buffer
                # files overwrite, so a re-dispatched batch is expected to skew the
                # exact match — that case warns instead of failing.
                retried = retried_batches.get(str(schema.id), 0)
                if retried > 0:
                    self.stdout.write(
                        self.style.WARNING(
                            f"WARNING: {schema.name}: scd2 rows ({scd2_rows}) != buffer rows ({buffer_rows}) "
                            f"with {retried} re-dispatched batch(es) in the window — likely retry-replay skew, "
                            "verify manually"
                        )
                    )
                else:
                    violations.append(
                        f"{schema.name}: scd2 lane rows ({scd2_rows}) != buffer rows ({buffer_rows}) — "
                        "exact match expected"
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
            ls_result = s3.ls(prefix, detail=True)
        except FileNotFoundError:
            return 0, 0, []
        # Some fsspec ls implementations return a dict keyed by path.
        entries = ls_result.values() if isinstance(ls_result, dict) else ls_result

        violations: list[str] = []
        named: list[tuple[str, BufferFileSpan]] = []
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
        for key, span in named:
            if span.start_seq > span.end_seq:
                violations.append(f"{schema.name}: inverted range in {key}")
            if prev_end is not None and span.start_seq < prev_end:
                violations.append(f"{schema.name}: overlapping range in {key} (starts before previous end {prev_end})")
            prev_end = span.end_seq

            # A failed shadow write can leave a truncated object; report it as a
            # violation instead of crashing the whole validation run.
            try:
                with s3.open(key, "rb") as f:
                    row_sum += pq.ParquetFile(f).metadata.num_rows
            except Exception as e:
                violations.append(f"{schema.name}: unreadable buffer file {key} ({type(e).__name__})")

        return row_sum, len(named), violations

    def _fetch_legacy_row_sums(
        self, source: ExternalDataSource, cutoff: datetime
    ) -> tuple[dict[tuple[str, str], int], dict[str, int]]:
        """Sum sourcebatch row_count per (schema_id, lane) since cutoff, plus the number of
        re-dispatched batches per schema (for retry-replay downgrades).

        Only `sync_type = 'cdc'` dispatches count: snapshots and resyncs flow into
        the same table as full_refresh/incremental and would otherwise inflate the
        consolidated lane into a guaranteed false violation. Lane is derived from
        resource_name via the shared companion suffix.

        A retry is a `(run_uuid, batch_index)` pair dispatched more than once — that is the
        replay the scd2 exact-match cannot survive. Counting distinct run_uuids instead (as this
        did originally) counts *scheduled ticks*: a healthy 5-min source mints a fresh run_uuid
        every tick, so any window longer than one tick looked like a retry and permanently
        downgraded the exact match to a warning, which is precisely the check this gate exists to
        make.
        """
        companion_pattern = "%" + CDC_COMPANION_SUFFIX.replace("_", r"\_")
        with psycopg.connect(WAREHOUSE_SOURCES_DATABASE_URL) as conn:
            rows = conn.execute(
                f"""
                SELECT schema_id, lane, COALESCE(SUM(batch_rows), 0), COUNT(*) FILTER (WHERE dispatches > 1)
                FROM (
                    SELECT schema_id,
                           CASE WHEN resource_name LIKE %(companion_pattern)s
                                THEN 'scd2' ELSE 'consolidated' END AS lane,
                           run_uuid,
                           batch_index,
                           SUM(row_count) AS batch_rows,
                           COUNT(*) AS dispatches
                    FROM {BATCH_TABLE}
                    WHERE source_id = %(source_id)s AND created_at >= %(cutoff)s AND sync_type = 'cdc'
                    GROUP BY schema_id, lane, run_uuid, batch_index
                ) per_batch
                GROUP BY schema_id, lane
                """,
                {"source_id": str(source.id), "cutoff": cutoff, "companion_pattern": companion_pattern},
            ).fetchall()

        sums: dict[tuple[str, str], int] = {}
        retried_batches: dict[str, int] = {}
        for schema_id, lane, total, retried in rows:
            sums[(str(schema_id), lane)] = int(total)
            retried_batches[str(schema_id)] = max(retried_batches.get(str(schema_id), 0), int(retried))
        return sums, retried_batches
