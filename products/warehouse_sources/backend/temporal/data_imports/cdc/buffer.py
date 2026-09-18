"""S3 change buffer for CDC — the ingress side of buffered CDC.

Capture demuxes decoded change events per schema and writes each micro-batch as
one Parquet file under a stable per-schema prefix:

    s3://{DATAWAREHOUSE_BUCKET}/cdc_producer/{team_id}/{schema_id}/{start_seq}-{end_seq}-{file_index}.parquet

The filename carries the batch's position range (`_ph_cdc_seq` min/max) zero-padded
to fixed width so lexicographic order equals numeric order — consumers sort by
filename, never by S3 mtime, and never parse Parquet to establish order.

`file_index` disambiguates batches that share a position range: a micro-flush can
split one transaction (all of whose events share a commit position) across
consecutive batches. Within a capture run the index is strictly increasing per
schema, so (start, end, index) sorts in WAL order.

Replay semantics: micro-batch boundaries are NOT deterministic across activity
attempts (the flush budget spans tables, the slot micro-advances mid-run, and a
soft deadline cuts runs on wall clock), so a retried attempt may cover the same
positions with differently-shaped files. Writers therefore call
`cleanup_superseded_files` before their first write per schema: every file that
reaches the position the retry re-reads from is superseded and removed, and a file
that straddles that position first has its settled rows rewritten under a narrower
range. A schema reset (TRUNCATE / lost slot) invalidates the whole prefix —
`purge_buffer_prefix`.

Two lanes write here. Shadow (the `dwh-cdc-buffer-shadow` feature flag, per team,
evaluated once per extraction run and fail-closed) writes a validation copy while
legacy delivery stays authoritative. Buffered ingress (`cdc_ingest_mode="buffered"`
in the source's `job_inputs`) writes the same files as the ONLY delivery — the
scheduled sync consumes them, and a write failure fails the run rather than being
swallowed, because the slot is about to advance past those changes.

Retention: an S3 lifecycle rule on `cdc_producer/` (`expire-cdc-producer-buffer`)
expires files after 14 days. Resets and CDC-disable purge sooner. For a buffered
schema, expiry of unconsumed files is unrecoverable — the slot advanced long ago —
so consumer lag is watched against file age, not file count.
"""

from __future__ import annotations

import re
import time
from contextlib import suppress
from dataclasses import dataclass

from django.conf import settings

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import posthoganalytics
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen

from products.data_warehouse.backend.facade.api import get_s3_client
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import CDC_SEQ_COLUMN
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.common import (
    ensure_bucket,
    strip_s3_protocol,
)

BUFFER_ROOT_FOLDER = "cdc_producer"

# Per-team gate for the shadow lane — the single on/off control. Fail-closed on
# evaluation errors, so the soak can only ever shrink, never grow, by accident.
SHADOW_WRITE_FLAG = "dwh-cdc-buffer-shadow"

_SEQ_WIDTH = 20  # zero-pad width covering the full u64 range
_INDEX_WIDTH = 6

# ASCII digits only: int() also accepts "+", "_", whitespace, and Unicode digits,
# any of which would break "lexicographic order equals numeric order".
_FILE_NAME_RE = re.compile(rf"([0-9]{{{_SEQ_WIDTH}}})-([0-9]{{{_SEQ_WIDTH}}})-([0-9]{{{_INDEX_WIDTH}}})\.parquet")
# A trimmed replacement is written under this suffix first. The consumer parses names, so it
# never reads a staged file, and the original can be removed before the replacement appears.
_STAGING_SUFFIX = ".staging"


def is_shadow_write_enabled(team_id: int, logger: FilteringBoundLogger) -> bool:
    """Whether the shadow lane may write for this team, evaluated once per run.

    Never raises: a flag-service failure leaves the lane off, which costs a gap in
    validation data — the legacy path is unaffected either way.
    """
    from posthog.models.team import Team

    try:
        team = Team.objects.get(pk=team_id)
        return bool(
            posthoganalytics.feature_enabled(
                SHADOW_WRITE_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                # team_id drives the release conditions (the warehouse convention for
                # per-team rollouts); the group context is passed for consistency with
                # the other warehouse flags and for org-wide kill switches.
                person_properties={"team_id": str(team.id)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id)},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.warning("cdc_shadow_flag_check_failed", team_id=team_id, exc_info=True)
        return False


def get_buffer_prefix(team_id: int, schema_id: str) -> str:
    return f"s3://{settings.DATAWAREHOUSE_BUCKET}/{BUFFER_ROOT_FOLDER}/{team_id}/{schema_id}"


def build_buffer_file_name(start_seq: int, end_seq: int, file_index: int) -> str:
    if not (0 <= start_seq <= end_seq < 10**_SEQ_WIDTH):
        raise ValueError(f"Invalid buffer position range: {start_seq}-{end_seq}")
    if not (0 <= file_index < 10**_INDEX_WIDTH):
        raise ValueError(f"Buffer file index out of range: {file_index}")
    return f"{start_seq:0{_SEQ_WIDTH}d}-{end_seq:0{_SEQ_WIDTH}d}-{file_index:0{_INDEX_WIDTH}d}.parquet"


@frozen
class BufferFileSpan:
    start_seq: int
    end_seq: int
    file_index: int


def parse_buffer_file_name(file_name: str) -> BufferFileSpan | None:
    """Parse `{start}-{end}-{index}.parquet` into the batch's position span.

    Returns None for names that don't match the contract (foreign files are
    ignored, never treated as buffer data).
    """
    match = _FILE_NAME_RE.fullmatch(file_name)
    if match is None:
        return None
    return BufferFileSpan(
        start_seq=int(match.group(1)),
        end_seq=int(match.group(2)),
        file_index=int(match.group(3)),
    )


@dataclass(frozen=True, slots=True)
class BufferFileWriteResult:
    s3_path: str
    row_count: int
    start_seq: int
    end_seq: int
    file_index: int
    write_duration_seconds: float


class CDCBufferWriter:
    """Writes per-schema change batches to the S3 buffer.

    The table must carry `_ph_cdc_seq` (engine-neutral monotonic position per row);
    the file's position range is derived from it.
    """

    def __init__(self, logger: FilteringBoundLogger) -> None:
        self._logger = logger
        self._s3 = get_s3_client()
        ensure_bucket()

    def write_batch(
        self,
        *,
        team_id: int,
        schema_id: str,
        table: pa.Table,
        file_index: int,
    ) -> BufferFileWriteResult:
        if CDC_SEQ_COLUMN not in table.column_names:
            raise ValueError(f"Buffer batches must carry {CDC_SEQ_COLUMN}")
        if table.num_rows == 0:
            raise ValueError("Refusing to write an empty buffer file")
        seq_column = table.column(CDC_SEQ_COLUMN)
        # Any null (not just all-null) is rejected: pc.min_max skips nulls, so a
        # partially-null column would silently narrow the filename's range.
        if seq_column.null_count != 0:
            raise ValueError(f"{CDC_SEQ_COLUMN} must be non-null in buffer batches")

        min_max = pc.min_max(seq_column)
        start_seq = min_max["min"].as_py()
        end_seq = min_max["max"].as_py()

        file_name = build_buffer_file_name(start_seq, end_seq, file_index)
        s3_path = f"{get_buffer_prefix(team_id, schema_id)}/{file_name}"
        key = strip_s3_protocol(s3_path)

        write_start = time.perf_counter()
        try:
            with self._s3.open(key, "wb") as f:
                pq.write_table(table, f, compression="zstd")
        except Exception:
            # fsspec's close() flushes buffered bytes even after a mid-write
            # failure, so a truncated object can land under a contract-valid
            # name. Best-effort removal keeps the failure a gap, not corruption.
            with suppress(Exception):
                self._s3.rm(key)
            raise
        write_duration = time.perf_counter() - write_start

        self._logger.debug(
            "cdc_buffer_file_written",
            s3_path=s3_path,
            row_count=table.num_rows,
            start_seq=start_seq,
            end_seq=end_seq,
            file_index=file_index,
        )

        return BufferFileWriteResult(
            s3_path=s3_path,
            row_count=table.num_rows,
            start_seq=start_seq,
            end_seq=end_seq,
            file_index=file_index,
            write_duration_seconds=write_duration,
        )

    def cleanup_superseded_files(self, *, team_id: int, schema_id: str, restart_seq: int) -> int:
        """Remove every file that reaches `restart_seq`, the position a retry re-reads from.

        A file that straddles it holds settled rows the WAL no longer has beside a
        transaction head the retry re-emits, so its settled rows are rewritten first.
        A surviving superseded file means a second copy of every position the retry
        writes, so failures propagate and the attempt retries. Returns files removed.
        """
        prefix = strip_s3_protocol(get_buffer_prefix(team_id, schema_id))
        try:
            # refresh: the fsspec instance cache can serve a stale listing in a
            # long-lived worker; a missed entry here silently skips a supersede-delete.
            keys = self._s3.ls(prefix, detail=False, refresh=True)
        except FileNotFoundError:
            return 0

        keys = self._promote_staged_files(keys)
        removed = 0
        trimmed = 0
        for key in keys:
            parsed = parse_buffer_file_name(key.rsplit("/", 1)[-1])
            if parsed is None or parsed.end_seq < restart_seq:
                continue
            staged = None
            if parsed.start_seq < restart_seq:
                staged = self._stage_settled_rows(key, file_index=parsed.file_index, restart_seq=restart_seq)
                if staged is not None:
                    trimmed += 1
            # The consumer may already have deleted an applied file.
            with suppress(FileNotFoundError):
                self._s3.rm(key)
            removed += 1
            if staged is not None:
                self._promote(staged)
        if removed:
            self._logger.info(
                "cdc_buffer_superseded_files_removed",
                schema_id=schema_id,
                restart_seq=restart_seq,
                removed=removed,
                trimmed=trimmed,
            )
        return removed

    def _stage_settled_rows(self, key: str, *, file_index: int, restart_seq: int) -> str | None:
        """Write a straddling file's rows below `restart_seq` to a staged file, and return its key.

        The final name keeps the original's start and index under a narrowed range, so it sorts
        where the original did. Staged first because a listing that saw both the original and
        the replacement would hand the history table the settled rows twice.
        """
        try:
            with self._s3.open(key, "rb") as f:
                table = pq.read_table(f)
        except FileNotFoundError:
            return None
        settled = table.filter(pc.less(table.column(CDC_SEQ_COLUMN), pa.scalar(restart_seq, type=pa.int64())))
        if settled.num_rows == 0:
            return None
        start_seq = pc.min(settled.column(CDC_SEQ_COLUMN)).as_py()
        end_seq = pc.max(settled.column(CDC_SEQ_COLUMN)).as_py()
        final_key = f"{key.rsplit('/', 1)[0]}/{build_buffer_file_name(start_seq, end_seq, file_index)}"
        staged_key = final_key + _STAGING_SUFFIX
        with self._s3.open(staged_key, "wb") as f:
            pq.write_table(settled, f, compression="zstd")
        return staged_key

    def _promote(self, staged_key: str) -> None:
        with self._s3.open(staged_key, "rb") as f:
            table = pq.read_table(f)
        with self._s3.open(staged_key.removesuffix(_STAGING_SUFFIX), "wb") as f:
            pq.write_table(table, f, compression="zstd")
        with suppress(FileNotFoundError):
            self._s3.rm(staged_key)

    def _promote_staged_files(self, keys: list[str]) -> list[str]:
        """Finish a cleanup a crash interrupted: a staged file always holds settled rows.

        If its original is still there, the crash came before the delete, so the original goes
        first. Returns the listing without the staged names and their originals.
        """
        remaining = list(keys)
        for key in keys:
            if not key.endswith(_STAGING_SUFFIX):
                continue
            final_key = key.removesuffix(_STAGING_SUFFIX)
            final = parse_buffer_file_name(final_key.rsplit("/", 1)[-1])
            if final is None:
                continue
            for other in keys:
                span = parse_buffer_file_name(other.rsplit("/", 1)[-1])
                if span is None or span == final:
                    continue
                if span.start_seq == final.start_seq and span.file_index == final.file_index:
                    with suppress(FileNotFoundError):
                        self._s3.rm(other)
                    if other in remaining:
                        remaining.remove(other)
            self._promote(key)
            remaining.remove(key)
            remaining.append(final_key)
        return remaining


def purge_buffer_prefix(team_id: int, schema_id: str, logger: FilteringBoundLogger, *, strict: bool = False) -> None:
    """Remove a schema's entire buffer prefix.

    Called on schema reset (TRUNCATE / lost-slot re-snapshot) and again right before the
    snapshot→streaming flip: the table is wiped and re-seeded through the snapshot lane the
    buffer never sees, so every existing buffer file predates a discontinuity no consumer
    could order across. Best-effort by default; `strict` propagates failures (except a
    missing prefix) for callers where a survived stale file would corrupt the table.
    """
    prefix = strip_s3_protocol(get_buffer_prefix(team_id, schema_id))
    try:
        s3 = get_s3_client()
        s3.rm(prefix, recursive=True)
        logger.info("cdc_buffer_prefix_purged", schema_id=schema_id)
    except FileNotFoundError:
        pass
    except Exception:
        if strict:
            raise
        logger.warning("cdc_buffer_prefix_purge_failed", schema_id=schema_id, exc_info=True)
