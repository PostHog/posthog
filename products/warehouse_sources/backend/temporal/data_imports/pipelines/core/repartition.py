"""In-place, streaming repartitioning of a DeltaLake table.

Incremental syncs merge new rows into a Delta table partition-by-partition, but delta-rs reads the
*whole* target partition into worker memory to do it. Once a single partition grows past ~1.5 GB
at-rest it OOMs the worker. The historical fix was a reset + full resync that re-pulls every row from
the source. This module instead repartitions the data **already in S3**, streaming one record-batch
at a time, so it never re-extracts from the source and never materialises an oversized partition.

The rewrite is a pure map (recompute `_ph_partition_key` per row under a finer scheme) into a sibling
temp table, followed by a crash-safe swap. The live table is never mutated until a fully-built temp
table exists, and temp stays the source of truth until the swap is verified — so a worker death at any
point loses at most wasted compute, never data. See the "Repartitioning" section in
`products/warehouse_sources/backend/temporal/data_imports/README.md`.
"""

from __future__ import annotations

import re
import math
import time
import asyncio
import dataclasses
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, NoReturn

import pyarrow as pa
import deltalake as deltalake
import pyarrow.compute as pc
import deltalake.exceptions
from structlog.types import FilteringBoundLogger

from posthog.temporal.common.utils import retry_on_db_connection_drop

from products.data_warehouse.backend.facade.api import aget_s3_client
from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    finalize_repartition_scheme,
    save_repartition_checkpoint_if_claimed,
    stage_partition_scheme_for_full_refresh,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    evolve_pyarrow_schema,
    normalize_column_name,
    realign_decimal_buffers,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.memory_governor import get_governor
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import _purge_s3_prefix
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.partitioning import (
    NULL_NUMERICAL_PARTITION,
    append_partition_key_to_table,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition_stream import (
    PartitionedFileWriter,
    SourceReader,
    StreamBudget,
    TempTableCommitter,
    UnsupportedSourceTableError,
    arrow_schema_of,
    check_source_supported,
    copied_source_files,
    plan_source_files,
    resume_blocker,
    storage_filesystem,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    PartitionFormat,
    PartitionMode,
)
from products.warehouse_sources.backend.temporal.data_imports.workload_report import report_buffer_bytes
from products.warehouse_sources.backend.types import IncrementalFieldType

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef

# Coarse → fine. A datetime table that's OOMing steps one tier finer each repartition cycle.
DATETIME_FORMAT_TIERS: list[PartitionFormat] = ["month", "week", "day", "hour"]

# Memory one rewrite may use when the pod's memory governor cannot size a slot (no cgroup limit).
DEFAULT_REWRITE_BUDGET_BYTES = 512 * 1024 * 1024
# A slot smaller than this cannot hold one decoded batch and a few open files; a slot larger than this
# buys no throughput, because the rewrite is bound by object-store reads, not by its buffers.
MIN_REWRITE_BUDGET_BYTES = 256 * 1024 * 1024
MAX_REWRITE_BUDGET_BYTES = 2 * 1024 * 1024 * 1024

# Minimum gap between claim re-reads during the rewrite loop. The loop reads at least one batch per
# source *file*, so an over-fragmented table (the exact kind being repartitioned) produces one batch
# per partition however small the budget makes the batches — a few thousand rows spread over a few
# thousand hour-partitions is a few thousand batches. Re-reading the claim on every one turns a small
# rewrite into thousands of Postgres round-trips, and any single failure discards the whole rewrite.
# Throttling is safe because the rewrite writes only to a temp table scoped to our own claim token
# (`_temp_uri_for`), so a superseded writer cannot reach a newer attempt's rebuild no matter how long
# it keeps going; the claim's real teeth are the unthrottled checks around the destructive swap steps.
# 0 disables the throttle (check every batch).
CLAIM_RECHECK_INTERVAL_SECONDS = 10.0

# Minimum gap between rewrite checkpoints. The deadline handler saves one too, but only a rewrite that
# survives to raise can reach it: an OOM-killed worker takes SIGKILL, so no `except` or `finally` runs
# and nothing is persisted. That left every memory death restarting from row 0 forever. Checkpointing
# on committed progress instead means an attempt converges across runs whatever kills it. Throttled
# because it costs a claim check and a row write per checkpoint, and bounds re-done work to this
# interval rather than to the whole rewrite. A checkpoint only records committed rows, so this also
# bounds how long the rewrite may go between commits — one that fills its buffers slower than this
# would otherwise leave the rewrite with nothing to resume from.
CHECKPOINT_INTERVAL_SECONDS = 30.0

# How long a rewrite that must stop keeps working toward its next source-file boundary. The rewrite
# can only commit there, so a stop inside a file discards the rows read since the last commit. One
# large source file can take longer to copy than a worker shutdown should wait, so after this long
# the rewrite stops without the commit and the next attempt reads that file again.
STOP_GRACE_SECONDS = 120.0

TEMP_URI_SUFFIX = "__repartitioned"


class RepartitionUnpartitionableError(Exception):
    """The table has no column suitable for partitioning — repartition is skipped, not retried."""


class RepartitionTooLargeForBudgetError(Exception):
    """One activity budget already failed to cover this table, and its checkpoint cannot be resumed.

    A rewrite that runs out of budget resumes only while live stays at the Delta version its
    checkpoint was built against, and the schema's own merge moves that version between runs. The
    restart that follows re-streams from row 0, with the same budget, over a table that has only
    grown, so it runs out in the same place and is discarded again on the next run. Three of those
    spend the attempt cap and the controller abandons the rewrite terminally, having spent a full
    budget per run to learn nothing. Raised instead of starting that restart, and terminal like
    `RepartitionUnpartitionableError`: the flag is cleared and the cooldown engaged, so the table is
    measured again on a later cycle rather than re-streamed on every sync.
    """


class RepartitionBudgetExceededError(Exception):
    """The rewrite ran out of activity budget before it finished streaming the table.

    Raised by the rewrite loop on reaching the deadline derived from the activity's
    `start_to_close_timeout`. It exists so the activity observes its own budget exhaustion instead of
    being killed by Temporal, which records nothing: the killed attempt keeps running as a zombie
    until a claim check makes it stand down, standing down burns no attempt, so
    `MAX_REPARTITION_ATTEMPTS` is never reached and the table re-enters the rewrite ahead of every
    later sync forever.

    Carries the partial progress (`rows_written`, `resolved`) so the caller can checkpoint the
    half-built temp table: the next attempt resumes appending from that offset rather than
    re-streaming from row 0, letting a table too large to rewrite in one activity converge across
    attempts instead of failing the same way every time.

    `resumed_from` is how many rows this attempt inherited: 0 when it started fresh, either because it
    is the first attempt or because the resume path rejected the prior checkpoint. The caller needs it
    to tell convergence from a treadmill. `rows_written` alone cannot: a rewrite that restarts every
    run writes hundreds of millions of rows each time and still ends where it began.

    `resumed_from == 0` alone can't tell a genuine first attempt from a treadmill restart, though — both
    inherit nothing. `had_prior_checkpoint` splits them: True means this attempt found a checkpoint it
    could build on (so re-covering ground from row 0 is a restart, not progress), False means there was
    none to inherit or the resume path rejected the one there was, because nobody has spent a budget
    on the rows a restart past a rejected checkpoint covers. `checkpoint_saved` records whether this attempt
    persisted a checkpoint the next run can resume from. A fresh first attempt that saved one is forward
    progress; the caller sets both.
    """

    def __init__(
        self,
        message: str,
        *,
        rows_written: int = 0,
        resolved: RepartitionTarget | None = None,
        resumed_from: int = 0,
        had_prior_checkpoint: bool = False,
        checkpoint_saved: bool = False,
    ) -> None:
        super().__init__(message)
        self.rows_written = rows_written
        self.resolved = resolved
        self.resumed_from = resumed_from
        self.had_prior_checkpoint = had_prior_checkpoint
        self.checkpoint_saved = checkpoint_saved


class RepartitionStoppedError(Exception):
    """The rewrite stopped early because its caller asked it to, for example on worker shutdown.

    Not a failure. Temp holds every row of the source files its commits record, and the rewrite
    checkpoint points at it, so the next attempt copies only the other files. `rows_written` counts
    the rows this attempt committed.
    """

    def __init__(self, message: str, *, rows_written: int = 0) -> None:
        super().__init__(message)
        self.rows_written = rows_written


class RepartitionSchemePersistError(Exception):
    """The swap re-bucketed the table in S3 but the new scheme could not be saved to the schema row.

    Never treated as transient noise, however transient the underlying database error was. The data in
    S3 now carries `_ph_partition_key` values the schema row does not describe, and the incremental
    merge scopes its predicate to `target._ph_partition_key = '<partition>'`: under that mismatch
    nothing matches and every fetched row inserts instead of upserting, duplicating the whole
    incremental lookback window with the job still reporting Completed.

    The `repartition_swap` marker stays set, which holds this schema's imports until a later run
    finishes the write — from the marker's recorded scheme, with no rebuild.
    """


class RepartitionSupersededError(Exception):
    """A newer repartition attempt has claimed this schema — this stale attempt must stop.

    An activity that Temporal heartbeat-times-out keeps running as a zombie (heartbeat failures are
    swallowed by HeartbeaterSync), so its retry starts while it is still rewriting. Two writers on the
    same table corrupt each other's temp `_delta_log` and defeat the swap's row-count verification.
    The schema row's `repartition_claim` is the fence: the newest claimant owns the table, and every
    destructive step re-checks the claim and raises this to make older attempts stand down.
    """


class RepartitionAttemptsExhausted(Exception):
    """Every one of `MAX_REPARTITION_ATTEMPTS` rewrites was charged but none survived to record an
    outcome, so the controller gives up and backs the table off to the daily cooldown.

    One attempt is charged per sync run before the rewrite runs, and refunded on a clean stand-down
    (supersession, cancellation, transient infra), so reaching the cap this way means the rewrite was
    hard-killed in every one of those runs — worker OOM, activity timeout, or an eviction that didn't
    surface as a cancellation — before it could fail cleanly or checkpoint progress. Terminal, and unlike a caught failure it
    carries no underlying exception, so the give-up path constructs and captures this to keep the most
    severe repartition outcome visible in error tracking rather than silently abandoned.
    """


@dataclasses.dataclass(frozen=True)
class RepartitionTarget:
    """The partition scheme to rewrite a table into. `partition_mode=None` means auto-detect."""

    partition_keys: list[str]
    trigger_reason: str
    partition_mode: PartitionMode | None = None
    partition_format: PartitionFormat | None = None
    partition_count: int | None = None
    partition_size: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RepartitionTarget:
        fields = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in fields})


# Delta's fixed marker for a Hive-style partition directory whose column value is null.
_HIVE_NULL_PARTITION = "__HIVE_DEFAULT_PARTITION__"


def _partition_key_from_add_path(path: str) -> str | None:
    """Recover the `_ph_partition_key` value from a Hive-style partitioned add-action file path.

    Every value this pipeline actually partitions by — an md5 bucket index, a numerical bucket or the
    `null` sentinel, or a datetime tier like "2024-01" — is plain ASCII with nothing that needs
    percent-encoding, so splitting the path recovers the same value `get_add_actions`'s
    `partition.<key>` column would give.
    """
    prefix = f"{PARTITION_KEY}="
    for segment in path.split("/"):
        if segment.startswith(prefix):
            value = segment[len(prefix) :]
            return None if value == _HIVE_NULL_PARTITION else value
    return None


def measure_partition_bytes(delta_table: deltalake.DeltaTable) -> dict[str | None, int]:
    """At-rest bytes per partition, read from the Delta log (no S3 LIST, no data scan).

    Unpartitioned tables collapse to a single `None` bucket. Keyed by the `_ph_partition_key` value.

    Reads `get_add_file_sizes` (file path -> size only), not `get_add_actions`: the latter also
    materializes every column's min/max/null-count stats into Arrow arrays, and a table with enough
    files can push a single stats column past Arrow's 2^31-byte offset limit for a default
    (32-bit-offset) string array, raising `Offset overflow error` and aborting detection for an
    otherwise healthy table.
    """
    partitioned = PARTITION_KEY in (delta_table.metadata().partition_columns or [])

    totals: dict[str | None, int] = defaultdict(int)
    for path, size in delta_table._table.get_add_file_sizes().items():
        key = _partition_key_from_add_path(path) if partitioned else None
        totals[key] += size or 0
    return dict(totals)


def _table_row_count(delta_table: deltalake.DeltaTable) -> int:
    """Total rows from the Delta log's per-file `num_records` (metadata only, no scan)."""
    actions = delta_table.get_add_actions(flatten=True)
    if "num_records" not in actions.schema.names:
        # Fall back to a metadata-only count if the stat is unavailable.
        return delta_table.to_pyarrow_dataset().count_rows()
    return sum(n or 0 for n in actions.column("num_records").to_pylist())


async def _valid_delta_row_count(uri: str, storage_options: dict[str, str]) -> int | None:
    """Open `uri` and return its row count, or None if it isn't a readable, complete Delta table.

    None means the folder is absent, not a Delta table, or its `_delta_log` is inconsistent (a
    DeltaError / FileNotFoundError from an interrupted write or swap). Used to gate destructive swap
    steps on the temp/live tables actually being intact, so a partial `__repartitioned` temp can never
    be copied over a good live table.
    """
    try:
        is_delta = await asyncio.to_thread(
            deltalake.DeltaTable.is_deltatable, table_uri=uri, storage_options=storage_options
        )
        if not is_delta:
            return None
        dt = await asyncio.to_thread(deltalake.DeltaTable, table_uri=uri, storage_options=storage_options)
        return await asyncio.to_thread(_table_row_count, dt)
    except (deltalake.exceptions.DeltaError, FileNotFoundError):
        return None


# Rows read from the live table to tell which partition scheme its data is bucketed under. The
# question is answered by recomputing one sample's keys, and every row of a scan-ordered sample is an
# equally good witness, so this only has to be large enough to survive a table whose first rows have
# a null partition key. Small enough to stay a single parquet row-group read.
LAYOUT_CHECK_SAMPLE_ROWS = 1_000


async def _live_matches_scheme(
    live_uri: str,
    storage_options: dict[str, str],
    target: RepartitionTarget,
    logger: FilteringBoundLogger,
    sample_rows: int = LAYOUT_CHECK_SAMPLE_ROWS,
) -> bool | None:
    """Whether the live table's stored `_ph_partition_key` values are the ones `target` produces.

    The schema row is the only record of which scheme the data in S3 was bucketed under, so a lost
    settings write leaves no way to tell the two schemes apart — except by asking the data. This reads
    a small sample of live rows, recomputes their partition key under `target`, and compares it with
    the value already stored on the row.

    True means the data is bucketed under `target`, False means it is not, and None means the question
    could not be answered: the table is unreadable or unpartitioned, the sample is empty, or `target`
    leaves the mode to auto-detection (which a sample can resolve differently from the full table, so
    a mismatch would say nothing). Callers must treat None as "unknown", never as "no".
    """
    if target.partition_mode is None:
        return None
    try:
        live_delta = await asyncio.to_thread(deltalake.DeltaTable, table_uri=live_uri, storage_options=storage_options)
        dataset = await asyncio.to_thread(live_delta.to_pyarrow_dataset)
        sample = await asyncio.to_thread(dataset.head, sample_rows)
    except Exception:
        # Every caller has a rebuild to fall back on, so a probe that cannot read the table answers
        # "unknown" rather than turning a recoverable state into a repartition failure.
        await logger.awarning("repartition: could not sample the live table's partition keys", exc_info=True)
        return None
    if sample.num_rows == 0 or PARTITION_KEY not in sample.column_names:
        return None

    stored = sample.column(PARTITION_KEY).cast(pa.string())
    result = append_partition_key_to_table(
        table=sample.drop([PARTITION_KEY]),
        partition_count=target.partition_count,
        partition_size=target.partition_size,
        partition_keys=target.partition_keys,
        partition_mode=target.partition_mode,
        partition_format=target.partition_format,
        logger=logger,
    )
    if result is None:
        return None
    recomputed = result.table.column(PARTITION_KEY).cast(pa.string())
    # Counted rather than reduced with `all`, which skips nulls: a null on either side is a row this
    # cannot vouch for, and the only use of True is to skip a rebuild, so it has to mean every row.
    matched = pc.sum(pc.equal(recomputed, stored).cast(pa.int64())).as_py()
    return matched == sample.num_rows


async def _persist_resolved_scheme(
    schema: ExternalDataSchema,
    resolved: RepartitionTarget,
    claim_token: str | None,
    logger: FilteringBoundLogger,
) -> None:
    """Save the scheme the swap just put on disk, and retire the repartition markers with it.

    Raises `RepartitionSchemePersistError` if the write does not land: the table's data and its
    settings disagree from here until it does, so this is the one failure in the whole flow that the
    sync must not shrug off. Retried once on a dropped pooled connection — the swap is already done,
    and losing this small write to a pgbouncer recycle is the likeliest way to reach that state.
    """

    def _write() -> bool:
        return finalize_repartition_scheme(
            schema,
            partitioning_keys=resolved.partition_keys,
            partition_count=resolved.partition_count,
            partition_size=resolved.partition_size,
            partition_mode=resolved.partition_mode,
            partition_format=resolved.partition_format,
            claim_token=claim_token,
        )

    try:
        wrote = await asyncio.to_thread(retry_on_db_connection_drop, _write)
    except Exception as e:
        raise RepartitionSchemePersistError(
            f"repartition: the swap landed but the new scheme could not be saved "
            f"(schema_id={schema.id} scheme={_format_scheme(resolved)}): {e}"
        ) from e
    if not wrote:
        # A newer attempt owns the schema now. It re-drives the swap from the marker we left set, so
        # standing down here loses nothing — and writing settings under its claim could describe a
        # layout it is in the middle of replacing.
        raise RepartitionSupersededError(
            f"repartition claim lost before the new scheme could be saved schema_id={schema.id}"
        )
    await logger.ainfo(
        f"repartition: saved new scheme scheme={_format_scheme(resolved)} schema_id={schema.id}",
        scheme=_format_scheme(resolved),
        schema_id=str(schema.id),
    )


async def _purge_stale_temp_tables(s3: Any, live_uri: str) -> None:
    """Delete every `{live_uri}__repartitioned*` temp variant before a fresh rebuild.

    Temp URIs are claim-scoped (`__repartitioned_<token>`), so a superseded or crashed attempt leaves
    an orphaned temp folder under its own token. Sweeping by name prefix clears them all — including
    the legacy unsuffixed `__repartitioned` — so orphans never accumulate S3 cost and a stale temp can
    never be mistaken for (or interleave with) the one this attempt is about to build.
    """
    s3.invalidate_cache()
    parent, _, table_dir = live_uri.rstrip("/").rpartition("/")
    if not parent or not table_dir:
        return
    files = await s3._find(parent, prefix=f"{table_dir}{TEMP_URI_SUFFIX}")
    if files:
        await s3._rm([f"s3://{f.lstrip('/')}" for f in files])


def _temp_uri_for(live_uri: str, claim_token: str | None) -> str:
    suffix = f"{TEMP_URI_SUFFIX}_{claim_token[:8]}" if claim_token else TEMP_URI_SUFFIX
    return f"{live_uri}{suffix}"


def _current_claim_token(schema: ExternalDataSchema) -> str | None:
    # Retry a dropped pooled connection: this read runs repeatedly across a rewrite that can span tens
    # of minutes, and pgbouncer recycling one connection under it would otherwise discard all of that
    # work — the read failing tells us nothing about whether we still hold the claim.
    retry_on_db_connection_drop(lambda: schema.refresh_from_db(fields=["sync_type_config"]))
    claim = schema.repartition_claim
    return claim.get("token") if claim else None


async def _ensure_claim(schema: ExternalDataSchema, claim_token: str | None) -> None:
    """Raise `RepartitionSupersededError` if a newer attempt has claimed the schema.

    Re-reads the schema row (the single, strongly-consistent coordination point — S3 has no locking)
    and compares tokens. `claim_token=None` means the caller opted out of fencing (tests, ad-hoc use).
    """
    if claim_token is None:
        return
    current = await asyncio.to_thread(_current_claim_token, schema)
    if current != claim_token:
        raise RepartitionSupersededError(
            f"repartition claim lost (ours={claim_token[:8]} current={str(current)[:8]}) schema_id={schema.id}"
        )


# Message shapes delta-rs / pyarrow raise when a table's log references an object gone from S3.
# "Object at location <path> not found" is the Rust `object_store` crate's NotFound display
# (github.com/apache/arrow-rs-object-store), surfaced through delta-rs; "File not found: <path>"
# is the datafusion/kernel scan variant. These are matched by exact wording, so a library upgrade
# that rewords them would silently stop recognizing the hole (fails safe to today's stuck loop, not
# data loss). `TestMissingLiveObjectRealError` provokes a real error from the installed deltalake and
# fails the moment the wording drifts past these patterns, so the drift can't rot unnoticed.
_MISSING_OBJECT_PATTERNS = (
    re.compile(r"Object at location (\S+)"),
    re.compile(r"File not found: (\S+)"),
)


def _missing_live_object_path(error: BaseException, live_uri: str) -> str | None:
    """Bucket-relative path of the missing S3 object `error` names, when it's a live-table data file.

    None for errors that don't name a missing object, name one outside the live table, or name one
    under a `__repartitioned` temp — only a hole in the live table itself warrants a revive.
    """
    message = str(error)
    path: str | None = None
    for pattern in _MISSING_OBJECT_PATTERNS:
        if match := pattern.search(message):
            path = match.group(1).rstrip(":,.")
            break
    if path is None:
        return None

    # The kernel reports bucket-relative paths; live_uri is s3://bucket/prefix. Normalize both.
    bucket, _, live_path = live_uri.split("://", 1)[-1].partition("/")
    live_path = live_path.rstrip("/")
    path = path.split("://", 1)[-1].lstrip("/")
    if path.startswith(f"{bucket}/"):
        path = path[len(bucket) + 1 :]
    # The trailing slash excludes `{live_path}__repartitioned*` temp siblings.
    if not live_path or not path.startswith(f"{live_path}/"):
        return None
    return path


async def _live_missing_data_file(live_uri: str, storage_options: dict[str, str], missing_path: str) -> str | None:
    """Absolute URI of `missing_path` when live's *current* log references it and the object is gone.

    Guards the revive against a stale-snapshot race: a reader whose table handle predates a
    legitimate rewrite also sees missing-object errors, but the current log no longer references
    those files — reviving then would needlessly reset a healthy table. Matches on basename (part
    file names embed a UUID, so they're unique) to sidestep the log's URL-encoded relative paths.
    """
    try:
        live_delta = await asyncio.to_thread(deltalake.DeltaTable, table_uri=live_uri, storage_options=storage_options)
        file_uris = await asyncio.to_thread(live_delta.file_uris)
    except (deltalake.exceptions.DeltaError, FileNotFoundError):
        # Live unreadable — the corrupted-log revive already covers that state.
        return None
    basename = missing_path.rsplit("/", 1)[-1]
    referenced = next((uri for uri in file_uris if uri.rsplit("/", 1)[-1] == basename), None)
    if referenced is None:
        return None
    async with aget_s3_client(fresh_instance=True) as s3:
        if await s3._exists(referenced):
            # The object exists after all — a transient read error, not a hollow table.
            return None
    return referenced


# Arrow/discovery type names that carry day granularity and no time-of-day component.
# Prefix-matched carefully: "datetime*"/"timestamp*" must NOT match.
_DATE_ONLY_COLUMN_TYPE_PREFIXES = ("date32", "date64")


def _datetime_tier_ceiling(schema: ExternalDataSchema) -> PartitionFormat:
    """The finest datetime tier that can physically split this schema's partition key.

    A date-typed key (e.g. Google Ads `segments.date`) carries no time-of-day, so every row of a
    day lands in the same `hour` bucket — an hour rewrite is a full-table rewrite that changes
    nothing, and afterwards the controller parks at "finest tier" with the table still OOMing.
    Cap such keys at `day`. Detected from either the incremental cursor being the partition key
    and declared `date`, or discovery metadata typing the key column as a date.
    """
    keys = schema.partitioning_keys or schema.primary_key_columns or []
    if len(keys) != 1:
        return DATETIME_FORMAT_TIERS[-1]
    key = normalize_column_name(keys[0])

    incremental_field = schema.incremental_field
    if (
        incremental_field is not None
        and normalize_column_name(incremental_field) == key
        and schema.incremental_field_type == IncrementalFieldType.Date
    ):
        return "day"

    for column in (schema.schema_metadata or {}).get("columns") or []:
        if not isinstance(column, dict):
            continue
        if normalize_column_name(str(column.get("name") or "")) != key:
            continue
        data_type = str(column.get("data_type") or "").lower()
        if data_type == "date" or data_type.startswith(_DATE_ONLY_COLUMN_TYPE_PREFIXES):
            return "day"

    return DATETIME_FORMAT_TIERS[-1]


def select_repartition_target(
    schema: ExternalDataSchema,
    partition_bytes: dict[str | None, int],
    target_partition_bytes: int,
) -> tuple[RepartitionTarget | None, str]:
    """Pick the next finer partition scheme, returning (target, reason).

    Computes the target directly from measured bytes so one repartition lands under budget rather
    than stepping blindly: md5 grows the bucket count, numerical shrinks the row-size, datetime steps
    one format tier finer. An unpartitioned table gets an auto target, which sizes its bucket count
    the same way so md5 is reachable whatever its keys turn out to be. When no target is chosen the
    reason explains why (reported in metrics so a skipped table is diagnosable): `within_budget`,
    `datetime_at_finest_tier` (only when there is no primary key distinct from the partition key to
    hash — otherwise a datetime table out of tiers falls back to md5), `numerical_cannot_shrink`,
    `numerical_no_size`, or `unpartitionable_no_keys`. A chosen target carries reason `selected`.
    """
    if not partition_bytes:
        return None, "no_partitions"

    max_bytes = max(partition_bytes.values())
    if max_bytes <= target_partition_bytes:
        return None, "within_budget"

    total_bytes = sum(partition_bytes.values())
    mode = schema.partition_mode
    keys = schema.partitioning_keys or schema.primary_key_columns or []

    if mode == "md5":
        current = schema.partition_count or len(partition_bytes) or 1
        new_count = max(current + 1, math.ceil(total_bytes / target_partition_bytes))
        return RepartitionTarget(
            partition_keys=keys, trigger_reason="", partition_mode="md5", partition_count=new_count
        ), "selected"

    if mode == "numerical":
        current_size = schema.partition_size
        if not current_size:
            return None, "numerical_no_size"
        new_size = max(1, math.floor(current_size * target_partition_bytes / max_bytes))
        if new_size >= current_size:
            return None, "numerical_cannot_shrink"
        return RepartitionTarget(
            partition_keys=keys, trigger_reason="", partition_mode="numerical", partition_size=new_size
        ), "selected"

    if mode == "datetime":
        current_format: PartitionFormat = schema.partition_format or "month"
        try:
            current_index = DATETIME_FORMAT_TIERS.index(current_format)
        except ValueError:
            current_index = 0
        # A date-granular key caps out at `day`; a table already at or past its ceiling (e.g.
        # no-op'd to `hour` before the ceiling existed) has nothing finer to gain either.
        ceiling_index = DATETIME_FORMAT_TIERS.index(_datetime_tier_ceiling(schema))
        if current_index >= ceiling_index:
            # No finer tier left, yet the table is still over budget. The key itself is skewed — a
            # backfill that stamped one timestamp across millions of rows puts more than the budget
            # in a single bucket, and splitting time more finely cannot divide rows that share a
            # value. md5 escapes that by bucketing on a hash rather than on the value, so partition
            # size follows the row count. It must hash the PRIMARY KEY, not the datetime partition
            # key: hashing the skewed column maps every row that shares a timestamp to the same
            # bucket and reproduces the skew exactly. The cost is time-range pruning at query time,
            # which an over-budget partition already outweighs by OOMing the merge and stalling the
            # sync. With no distinct primary key to hash there is nothing better to move to, so the
            # table stays parked at the finest tier for the caller to alert on.
            hash_keys = schema.primary_key_columns or []
            if not hash_keys or set(hash_keys) == set(keys):
                return None, "datetime_at_finest_tier"
            return RepartitionTarget(
                partition_keys=hash_keys,
                trigger_reason="",
                partition_mode="md5",
                partition_count=max(1, math.ceil(total_bytes / target_partition_bytes)),
            ), "selected"
        return RepartitionTarget(
            partition_keys=keys,
            trigger_reason="",
            partition_mode="datetime",
            partition_format=DATETIME_FORMAT_TIERS[current_index + 1],
        ), "selected"

    # Unpartitioned but over budget: attempt to enable partitioning via auto-detection. Needs keys.
    if not keys:
        return None, "unpartitionable_no_keys"
    # Carry a bucket count so md5 is always reachable. Auto-detection prefers numerical, then
    # datetime, and falls through to md5 only when neither applies — but md5 needs a count, and
    # without one a table whose keys suit none of the detectors (a UUID primary key and no
    # `created_at`-style column) has no scheme at all. It flags as over budget every day, fails the
    # rewrite with "No supported partition mode", and grows unbounded. Hashed keys bucket any key
    # type, and a primary key never changes, so a row keeps its bucket across merges.
    return RepartitionTarget(
        partition_keys=keys,
        trigger_reason="",
        partition_mode=None,
        partition_count=max(1, math.ceil(total_bytes / target_partition_bytes)),
    ), "selected"


# Coarsening (the reverse direction) rebuilds an over-fragmented table into fewer, larger partitions.
# It aims at half the budget, not the budget itself: landing at the budget would sit one growth spurt
# away from the finer trigger, and the gap between the two targets is what stops the controller
# oscillating. The minimum reduction keeps a rewrite from being spent on a marginal gain.
COARSEN_MIN_REDUCTION_FACTOR = 4

# Partition-key formats, by mode, for parsing a measured key back into the value that produced it.
_DATETIME_KEY_FORMATS: dict[PartitionFormat, str] = {
    "hour": "%Y-%m-%dT%H",
    "day": "%Y-%m-%d",
    "week": "%G-w%V",
    "month": "%Y-%m",
}

# Coarser tiers each partition can merge into, coarsest first. Every tier here contains the finer one
# whole, so a row's new bucket follows from its old key, except week into month: ISO weeks straddle
# month boundaries, and how a week's bytes divide between two months is not recoverable from the key.
# That one is sized by upper bound instead (see `simulate_datetime_coarsening`) rather than left
# unreachable, because the finer path's first step is month into week, so without it a table this
# controller wrongly split could never be merged back.
_COARSER_DATETIME_TIERS: dict[PartitionFormat, tuple[PartitionFormat, ...]] = {
    "hour": ("month", "week", "day"),
    "day": ("month", "week"),
    "week": ("month",),
    "month": (),
}


def _parse_datetime_partition_key(key: str, partition_format: PartitionFormat) -> datetime | None:
    if partition_format == "week":
        # %G/%V need a weekday to resolve to a date, so anchor on the week's Monday.
        return _strptime_or_none(f"{key}-1", "%G-w%V-%u")
    return _strptime_or_none(key, _DATETIME_KEY_FORMATS[partition_format])


def _strptime_or_none(value: str, fmt: str) -> datetime | None:
    try:
        return datetime.strptime(value, fmt)
    except ValueError:
        return None


def _merged_keys(parsed: datetime, current_format: PartitionFormat, new_format: PartitionFormat) -> list[str]:
    """The coarser bucket(s) a partition's bytes can land in.

    One bucket for every containing tier. Week into month is the exception: the week starting `parsed`
    runs to the following Sunday, so it can fall in two months, and the key does not say how its bytes
    divide. Both months are returned and each is charged the week's full size, which over-states rather
    than under-states every bucket it touches. A layout that fits under that bound fits in reality.
    """
    if current_format == "week" and new_format == "month":
        monday_month = parsed.strftime(_DATETIME_KEY_FORMATS["month"])
        sunday_month = (parsed + timedelta(days=6)).strftime(_DATETIME_KEY_FORMATS["month"])
        return [monday_month] if monday_month == sunday_month else [monday_month, sunday_month]
    return [parsed.strftime(_DATETIME_KEY_FORMATS[new_format])]


def simulate_datetime_coarsening(
    partition_bytes: dict[str | None, int],
    current_format: PartitionFormat,
    new_format: PartitionFormat,
) -> dict[str | None, int] | None:
    """Bytes per partition after re-bucketing measured partitions into `new_format`.

    Computed from the keys rather than estimated: partition keys carry the date they were built from,
    so every transition is exact except week into month, which is an upper bound (see `_merged_keys`).
    Both are safe to size a rewrite against, since neither can under-state a resulting partition.

    None when any key doesn't parse, because a table carrying the unknown-date sentinel or non-date
    keys must not be coarsened on a guess.
    """
    merged: dict[str | None, int] = defaultdict(int)
    for key, size in partition_bytes.items():
        if key is None:
            return None
        parsed = _parse_datetime_partition_key(key, current_format)
        if parsed is None:
            return None
        for merged_key in _merged_keys(parsed, current_format, new_format):
            merged[merged_key] += size
    return dict(merged)


def _simulate_modulo_coarsening(partition_bytes: dict[str | None, int], new_count: int) -> dict[str | None, int] | None:
    """Bytes per bucket after reducing an md5 scheme to `new_count` buckets.

    Exact only because `new_count` divides the current count: a row in bucket `h % N` lands in
    `(h % N) % M` when M divides N, so buckets merge cleanly instead of redistributing.
    """
    merged: dict[str | None, int] = defaultdict(int)
    for key, size in partition_bytes.items():
        if key is None or not key.isdigit():
            return None
        merged[str(int(key) % new_count)] += size
    return dict(merged)


def _simulate_numerical_coarsening(
    partition_bytes: dict[str | None, int], multiplier: int
) -> dict[str | None, int] | None:
    """Bytes per bucket after growing a numerical partition size by `multiplier`.

    Buckets are `value // size`, so a size of `size * k` merges exactly `k` adjacent buckets. The null
    bucket holds rows with no usable key and stays as it is.
    """
    merged: dict[str | None, int] = defaultdict(int)
    for key, size in partition_bytes.items():
        if key is None:
            return None
        if key == NULL_NUMERICAL_PARTITION:
            merged[key] += size
            continue
        try:
            bucket = int(key)
        except ValueError:
            return None
        merged[str(bucket // multiplier)] += size
    return dict(merged)


def select_coarsen_target(
    schema: ExternalDataSchema,
    partition_bytes: dict[str | None, int],
    target_partition_bytes: int,
) -> tuple[RepartitionTarget | None, str]:
    """Pick the coarsest partition scheme whose largest partition still fits `target_partition_bytes`.

    The mirror of `select_repartition_target`, for tables left over-fragmented, most of them by the
    finer path itself reacting to failures that were never about partition size. Fragmentation is not
    free: every partition is its own merge commit, so a table split into thousands of tiny pieces syncs
    slowly enough to cause the very timeouts that shrank it.

    Every candidate layout is simulated from the measured partitions rather than estimated, so a rewrite
    only happens when the result is known. Returns (target, reason); reasons mirror the finer path's.
    """
    if not partition_bytes:
        return None, "no_partitions"

    keys = schema.partitioning_keys or schema.primary_key_columns or []
    if not keys:
        # The rewrite recomputes every row's key, which needs a column to compute it from.
        return None, "unpartitionable_no_keys"
    mode = schema.partition_mode
    current_count = len(partition_bytes)

    def acceptable(simulated: dict[str | None, int] | None) -> bool:
        return (
            simulated is not None
            and max(simulated.values()) <= target_partition_bytes
            and len(simulated) * COARSEN_MIN_REDUCTION_FACTOR <= current_count
        )

    if mode == "datetime":
        current_format: PartitionFormat = schema.partition_format or "month"
        candidate_formats = _COARSER_DATETIME_TIERS.get(current_format)
        if candidate_formats is None:
            return None, "datetime_unknown_format"
        if not candidate_formats:
            return None, "datetime_at_coarsest_tier"
        # Coarsest tier first: fewer, larger partitions is the goal, and the size ceiling is what stops it.
        for new_format in candidate_formats:
            if acceptable(simulate_datetime_coarsening(partition_bytes, current_format, new_format)):
                return RepartitionTarget(
                    partition_keys=keys,
                    trigger_reason="",
                    partition_mode="datetime",
                    partition_format=new_format,
                ), "selected"
        return None, "no_coarser_layout_fits"

    if mode == "md5":
        count = schema.partition_count
        if not count:
            # The measured bucket count is no substitute: sparse data can leave buckets empty, and a
            # divisor of the measured count need not divide the true modulo, which is the whole basis
            # of the simulation's exactness ((h % N) % M == h % M only when M divides N).
            return None, "md5_no_count"
        # Every divisor of the current count is a candidate, because only a divisor merges buckets
        # cleanly (a row in bucket h % N lands in (h % N) % M exactly when M divides N), which is what
        # makes the simulation exact rather than an assumption about how md5 redistributes rows. The
        # finer path produces arbitrary counts, so halving alone would strand any non-power-of-two.
        divisors: set[int] = set()
        for low in range(1, math.isqrt(count) + 1):
            if count % low == 0:
                divisors.add(low)
                divisors.add(count // low)
        divisors.discard(count)
        for new_count in sorted(divisors):  # ascending, so the coarsest layout that fits wins
            if acceptable(_simulate_modulo_coarsening(partition_bytes, new_count)):
                return RepartitionTarget(
                    partition_keys=keys,
                    trigger_reason="",
                    partition_mode="md5",
                    partition_count=new_count,
                ), "selected"
        return None, "no_coarser_layout_fits"

    if mode == "numerical":
        current_size = schema.partition_size
        if not current_size:
            return None, "numerical_no_size"
        multiplier = 2 ** math.floor(math.log2(max(current_count, 1))) if current_count > 1 else 1
        while multiplier >= 2:
            if acceptable(_simulate_numerical_coarsening(partition_bytes, multiplier)):
                return RepartitionTarget(
                    partition_keys=keys,
                    trigger_reason="",
                    partition_mode="numerical",
                    partition_size=current_size * multiplier,
                ), "selected"
            multiplier //= 2
        return None, "no_coarser_layout_fits"

    return None, "unsupported_mode"


def _format_scheme(target: RepartitionTarget) -> str:
    """`datetime/month`, `md5/64`, `numerical/1000000` — the scheme in one readable token."""
    knob = target.partition_format or target.partition_count or target.partition_size
    return f"{target.partition_mode or 'auto'}/{knob}" if knob else (target.partition_mode or "auto")


def _format_fields(fields: dict[str, Any]) -> str:
    return " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)


def rewrite_budget() -> StreamBudget:
    """The rewrite's byte budget: one memory-governor slot, the same share a concurrent upsert gets."""
    slot_mb = get_governor().slot_budget_mb()
    budget = int(slot_mb * 1024 * 1024) if slot_mb else DEFAULT_REWRITE_BUDGET_BYTES
    return StreamBudget.from_budget(min(max(budget, MIN_REWRITE_BUDGET_BYTES), MAX_REWRITE_BUDGET_BYTES))


async def _delete_uncommitted(temp_uri: str, storage_options: dict[str, str], paths: list[str]) -> None:
    """Best effort: files no commit references are invisible, but the swap copies the whole prefix."""
    if not paths:
        return

    def delete() -> None:
        filesystem = storage_filesystem(temp_uri, storage_options)
        for path in paths:
            try:
                filesystem.delete_file(path)
            except Exception:
                pass

    await asyncio.to_thread(delete)


async def _rewrite_into_temp(
    *,
    old_delta: deltalake.DeltaTable,
    temp_uri: str,
    storage_options: dict[str, str],
    target: RepartitionTarget,
    logger: FilteringBoundLogger,
    budget: StreamBudget | None = None,
    ensure_claim: Callable[[], Awaitable[None]] | None = None,
    claim_recheck_interval_seconds: float = CLAIM_RECHECK_INTERVAL_SECONDS,
    save_checkpoint: Callable[[int, RepartitionTarget], Awaitable[None]] | None = None,
    checkpoint_interval_seconds: float = CHECKPOINT_INTERVAL_SECONDS,
    deadline: float | None = None,
    total_rows: int | None = None,
    copied_files: frozenset[str] = frozenset(),
    should_stop: Callable[[], bool] | None = None,
    stop_grace_seconds: float = STOP_GRACE_SECONDS,
) -> tuple[int, RepartitionTarget]:
    """Stream the live table into a temp table under the new partition scheme.

    Returns (rows_written, resolved_target) — `rows_written` counts only the rows committed by *this*
    call. The first processed batch resolves any auto-detected mode/format/keys so every subsequent
    batch is bucketed identically (a per-batch auto-detect could disagree). `ensure_claim` runs before
    the first batch and then at most once per `claim_recheck_interval_seconds`, so a superseded attempt
    stops within that window rather than paying a database round-trip per batch (see
    `CLAIM_RECHECK_INTERVAL_SECONDS`).

    Memory is bounded by `budget` alone (see `repartition_stream`): the rewrite plans from the log of
    the loaded version, reads one source file at a time by row group, and writes through a capped set
    of open files. It commits only at a source-file boundary, and each commit records the source
    files it completes.

    `deadline` is a `time.monotonic()` value past which the rewrite gives up with
    `RepartitionBudgetExceededError` rather than run until Temporal kills it. None runs unbounded.

    `total_rows` is the source row count, used only to report progress as a percentage and an ETA.

    `copied_files` resumes a prior attempt: temp already holds every row of these source files (see
    `copied_source_files`), so this call skips them and appends only the rest.

    `should_stop` asks the rewrite to stop early, for example because the worker is shutting down.
    Once it returns True the rewrite commits at the next source-file boundary, saves a checkpoint and
    raises `RepartitionStoppedError`. A source file that is still not finished `stop_grace_seconds`
    later is abandoned with the other uncommitted rows, and the next attempt reads it again.
    """
    budget = budget or rewrite_budget()
    await logger.ainfo(
        f"repartition: rewrite starting target_scheme={_format_scheme(target)} total_rows={total_rows} "
        f"batch_bytes={budget.batch_bytes} max_open_files={budget.max_open_files} temp_uri={temp_uri}",
        target_scheme=_format_scheme(target),
        total_rows=total_rows,
        temp_uri=temp_uri,
        **budget.to_dict(),
    )

    try:
        check_source_supported(old_delta)
    except UnsupportedSourceTableError as e:
        raise RepartitionUnpartitionableError(str(e)) from e

    # The live table's properties travel with its rows. A buffered CDC lane reads its resume
    # point from a statistic one of them declares, and a rebuilt table that lost it would report
    # no position at all.
    table_configuration = dict(old_delta.metadata().configuration or {})
    live_schema = await asyncio.to_thread(old_delta.schema)
    live_arrow_schema = arrow_schema_of(live_schema)
    plan = await asyncio.to_thread(plan_source_files, old_delta)
    inherited_rows = 0
    if copied_files:
        inherited_rows = sum(source.num_records or 0 for source in plan if source.path in copied_files)
        plan = [source for source in plan if source.path not in copied_files]
        await logger.ainfo(
            f"repartition: resume skips the {len(copied_files)} source files already copied, {len(plan)} left to copy",
            files_already_copied=len(copied_files),
            files_left=len(plan),
        )

    reader = SourceReader(
        filesystem=storage_filesystem(
            old_delta.table_uri, storage_options, known_sizes={source.path: source.size for source in plan}
        ),
        schema=live_arrow_schema,
        batch_bytes=budget.batch_bytes,
    )
    committer = TempTableCommitter(
        temp_uri=temp_uri, storage_options=storage_options, configuration=table_configuration
    )
    writer: PartitionedFileWriter | None = None

    async def run_io(function: Callable[..., Any], *args: Any) -> Any:
        """Do not let task cancellation abandon a native I/O call that still owns these objects."""
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await asyncio.shield(task)
            except BaseException:
                pass
            raise

    resolved: RepartitionTarget | None = None
    rows_written = 0
    started_at = time.monotonic()
    commits = 0

    def progress() -> dict[str, Any]:
        """Structured rewrite progress. One of these per commit is the whole story of a rewrite."""
        elapsed = max(time.monotonic() - started_at, 1e-6)
        rate = rows_written / elapsed
        fields: dict[str, Any] = {
            "rows_written": rows_written,
            "commits": commits,
            "elapsed_seconds": round(elapsed),
            "rows_per_second": round(rate),
        }
        if total_rows:
            fields["total_rows"] = total_rows
            fields["percent_complete"] = round(100 * rows_written / total_rows, 1)
            # Only meaningful once a commit has landed; before that there is no rate to project from.
            fields["eta_seconds"] = round(max(total_rows - rows_written, 0) / rate) if rate else None
        return fields

    last_checkpoint_at: float | None = None

    async def maybe_checkpoint(force: bool = False) -> None:
        """Persist resumable progress, at most once per `checkpoint_interval_seconds` unless forced.

        Called after a commit lands, so the recorded row count is always backed by data actually in
        temp. Failing to checkpoint must not fail the rewrite: the attempt is still making progress,
        and the next one simply resumes from further back.
        """
        nonlocal last_checkpoint_at
        if save_checkpoint is None:
            return
        now = time.monotonic()
        if not force and last_checkpoint_at is not None and now - last_checkpoint_at < checkpoint_interval_seconds:
            return
        last_checkpoint_at = now
        try:
            await save_checkpoint(rows_written, resolved or target)
        except RepartitionSupersededError:
            raise
        except Exception:
            await logger.awarning("repartition: could not save rewrite checkpoint", exc_info=True)

    completed_sources: list[str] = []
    last_commit_at = time.monotonic()

    async def commit() -> None:
        """Close the open files and commit them, with the source files whose rows they now hold."""
        nonlocal rows_written, commits, completed_sources, last_commit_at
        await write_staged()
        last_commit_at = time.monotonic()
        if writer is None or not completed_sources:
            return
        written = await run_io(writer.finish)
        await run_io(committer.commit, written, completed_sources)
        completed_sources = []
        rows_written += sum(file.num_records for file in written)
        commits += 1
        report_buffer_bytes(0)
        await maybe_checkpoint()
        fields = progress()
        await logger.ainfo(f"repartition: rewrite progress {_format_fields(fields)}", **fields)

    def prepare(table: pa.Table) -> pa.Table:
        nonlocal resolved
        if PARTITION_KEY in table.column_names:
            table = table.drop([PARTITION_KEY])
        # After the first batch resolves, later batches must use the *resolved* keys too: datetime
        # auto-detect swaps the key from the primary key to the detected timestamp column, and pairing
        # the resolved mode with the original (e.g. UUID) key would fail to parse it as a date.
        result = append_partition_key_to_table(
            table=table,
            partition_count=target.partition_count,
            partition_size=target.partition_size,
            partition_keys=resolved.partition_keys if resolved else target.partition_keys,
            partition_mode=resolved.partition_mode if resolved else target.partition_mode,
            partition_format=resolved.partition_format if resolved else target.partition_format,
            logger=logger,
        )
        if result is None:
            raise RepartitionUnpartitionableError(f"No supported partition mode for keys={target.partition_keys}")
        if resolved is None:
            resolved = dataclasses.replace(
                target,
                partition_mode=result.partition_mode,
                partition_format=result.partition_format,
                partition_keys=result.partition_keys,
            )
        # Align each batch against the live table's own declared schema before writing. Without
        # this, a column the live schema already declares non-nullable that slips through with a
        # real null (e.g. a source NOT NULL constraint later relaxed upstream) reaches the temp
        # table as a null in a non-nullable column. Every other Delta write path in this pipeline
        # runs incoming data through this same alignment first, so the rewrite must too.
        return realign_decimal_buffers(evolve_pyarrow_schema(result.table, live_schema))

    # Over-fragmented sources hand over a few rows per file. Partitioning, aligning and routing
    # each of those on its own costs more than the copy, so the reads are coalesced up to one batch
    # budget first.
    staged: list[pa.Table] = []
    staged_bytes = 0

    async def write_staged() -> None:
        nonlocal writer, staged, staged_bytes
        if not staged:
            return
        combined = staged[0] if len(staged) == 1 else pa.concat_tables(staged)
        staged = []
        staged_bytes = 0
        prepared = await run_io(prepare, combined)
        if writer is None:
            file_schema = await run_io(committer.open_or_create, prepared.schema)
            writer = PartitionedFileWriter(
                filesystem=storage_filesystem(temp_uri, storage_options),
                schema=file_schema,
                budget=budget,
                configuration=table_configuration,
            )
        await run_io(writer.write, prepared)
        # Feeds the workload reporter bound by the repartition activity; no-op everywhere else.
        report_buffer_bytes(writer.buffered_bytes)

    stop_requested_at: float | None = None

    def stop_requested() -> bool:
        nonlocal stop_requested_at
        if should_stop is None or not should_stop():
            return False
        if stop_requested_at is None:
            stop_requested_at = time.monotonic()
        return True

    async def stop() -> NoReturn:
        # The throttled checkpoint can be older than the last commit. The next attempt resumes only
        # from a checkpoint, so save one now. Without a commit from this attempt there is nothing new
        # to record, and temp may not exist yet.
        if commits:
            await maybe_checkpoint(force=True)
        fields = progress()
        await logger.ainfo(f"repartition: rewrite stopped early {_format_fields(fields)}", **fields)
        raise RepartitionStoppedError(
            f"rewrite stopped early after {rows_written} rows written to {temp_uri}", rows_written=rows_written
        )

    last_claim_check: float | None = None
    files_left = len(plan)
    sources = reader.iter_sources(plan)
    try:
        while True:
            entry = await run_io(next, sources, None)
            if entry is None:
                break
            source, tables = entry
            while True:
                if ensure_claim is not None:
                    now = time.monotonic()
                    if last_claim_check is None or now - last_claim_check >= claim_recheck_interval_seconds:
                        await ensure_claim()
                        last_claim_check = now
                table = await run_io(next, tables, None)
                if table is None:
                    break
                # Deliberately after the read, so exhausting the last file always beats the deadline.
                # Checking first would let a rewrite that has already copied every row be discarded
                # and charged an attempt because it happened to cross the deadline on the iteration
                # that would have hit EOF, which is likeliest for a table whose rewrite lands near the
                # budget: exactly the ones this deadline exists to rescue.
                if deadline is not None and time.monotonic() >= deadline:
                    raise RepartitionBudgetExceededError(
                        f"rewrite exceeded its activity budget after {rows_written} rows written to {temp_uri}",
                        rows_written=rows_written,
                        resolved=resolved,
                        resumed_from=inherited_rows,
                    )
                if (
                    stop_requested()
                    and stop_requested_at is not None
                    and time.monotonic() - stop_requested_at >= stop_grace_seconds
                ):
                    await stop()
                staged.append(table)
                staged_bytes += table.nbytes
                if staged_bytes >= budget.batch_bytes:
                    await write_staged()
            completed_sources.append(source.path)
            files_left -= 1
            # After the last file only the final commit is left, so finishing costs less than a stop
            # and a new attempt.
            stopping = files_left > 0 and stop_requested()
            if (
                (writer is not None and writer.bytes_since_commit >= budget.commit_bytes)
                or len(completed_sources) >= budget.max_source_files_per_commit
                or time.monotonic() - last_commit_at >= checkpoint_interval_seconds
                or stopping
            ):
                await commit()
            if stopping:
                await stop()
        await commit()
    except BaseException:
        if writer is not None:
            try:
                paths = await run_io(writer.abort)
                await _delete_uncommitted(temp_uri, storage_options, paths)
            except BaseException:
                await logger.awarning("repartition: could not clean up uncommitted files", exc_info=True)
        raise
    finally:
        try:
            await run_io(sources.close)
        except BaseException:
            await logger.awarning("repartition: could not close the source reader", exc_info=True)

    if resolved is None:
        # Empty source table — nothing to rewrite.
        resolved = target
    fields = progress()
    await logger.ainfo(
        f"repartition: rewrite complete scheme={_format_scheme(resolved)} {_format_fields(fields)}",
        scheme=_format_scheme(resolved),
        **fields,
    )
    return rows_written, resolved


async def _copied_source_files(temp_uri: str, storage_options: dict[str, str]) -> frozenset[str] | None:
    try:
        return await asyncio.to_thread(copied_source_files, temp_uri, storage_options)
    except (deltalake.exceptions.DeltaError, FileNotFoundError, ValueError):
        return None


def _restart_would_run_out_of_budget(checkpoint: dict[str, Any], live_rows: int) -> bool:
    """Whether re-streaming this table from row 0 would run out of budget the way the last attempt did.

    Only a checkpoint left behind by budget exhaustion says anything about the budget. One written by
    the periodic saves belongs to an attempt killed at an arbitrary point — a worker OOM ten minutes
    in — and the rows it covered measure nothing. `rows_written` from a budget-exhausted attempt is
    that measure, so a live table holding more rows than it cannot be rewritten in one budget either.
    """
    if not checkpoint.get("budget_exhausted"):
        return False
    covered = int(checkpoint.get("rows_written") or 0)
    return 0 < covered < live_rows


async def defer_repartition_to_full_refresh(
    table_ref: DeltaTableRef,
    schema: ExternalDataSchema,
    target: RepartitionTarget,
    logger: FilteringBoundLogger,
    *,
    claim_token: str | None = None,
) -> dict[str, Any]:
    """Apply `target` through the next full refresh instead of rewriting the table.

    A full-refresh sync deletes the table and writes every row again, so a rewrite only copies data
    the next sync throws away. Its live version also moves on every sync. The scheme is staged for
    that sync to write (see `stage_partition_scheme_for_full_refresh`). Temp tables are not swept
    here: a newer claimant can begin a recovery while this activity awaits S3, and wildcard cleanup
    cannot be fenced by the database claim for the duration of that operation.
    """

    def _write() -> bool:
        return stage_partition_scheme_for_full_refresh(
            schema,
            partitioning_keys=target.partition_keys,
            partition_count=target.partition_count,
            partition_size=target.partition_size,
            partition_mode=target.partition_mode,
            partition_format=target.partition_format,
            claim_token=claim_token,
        )

    if not await asyncio.to_thread(retry_on_db_connection_drop, _write):
        raise RepartitionSupersededError(f"repartition claim lost before full-refresh deferral schema_id={schema.id}")
    await logger.ainfo(
        f"repartition: full-refresh table, staged scheme={_format_scheme(target)} for the next sync to write "
        f"schema_id={schema.id}",
        scheme=_format_scheme(target),
        schema_id=str(schema.id),
    )
    return {"outcome": "deferred", "reason": "full_refresh_rewrites_the_table"}


async def repartition_table_in_place(
    table_ref: DeltaTableRef,
    schema: ExternalDataSchema,
    target: RepartitionTarget,
    logger: FilteringBoundLogger,
    *,
    budget: StreamBudget | None = None,
    claim_token: str | None = None,
    deadline: float | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Rewrite the schema's Delta table under `target`'s finer partition scheme, in place, from S3.

    Memory is bounded by `budget` (one memory-governor slot by default); the source is read once. Crash-safe via the
    `repartition_swap` marker (resume re-drives the swap from the intact temp table). On success,
    persists the new partition settings and clears the controller markers in one row-locked write.
    Returns a stats dict for observability. Raises `RepartitionUnpartitionableError` (terminal) if no
    partition mode applies, `RepartitionTooLargeForBudgetError` (terminal) if the table needs more
    than one activity budget and its checkpoint cannot be resumed, and `RepartitionSchemePersistError`
    if the swap lands but its scheme cannot be saved — the one failure the caller must not shrug off,
    since the table's data and its settings disagree until a later run finishes that write.

    `claim_token` fences out zombie attempts: the temp table is scoped to the token so concurrent
    writers can never share one, and the claim is re-checked before every destructive step — and,
    during the rewrite, at most once per `CLAIM_RECHECK_INTERVAL_SECONDS` (raising
    `RepartitionSupersededError` when a newer attempt has taken over).

    `deadline` (a `time.monotonic()` value) bounds the rewrite phase only. The swap that follows
    needs no bound of its own: it records `repartition_swap` before touching live, so a swap cut
    short by the activity timeout resumes from the intact temp table on a later run.

    `should_stop` also applies to the rewrite phase only. When it returns True the rewrite stops after
    its next commit and raises `RepartitionStoppedError`, with the temp table and its checkpoint kept
    for the next attempt (see `_rewrite_into_temp`).
    """
    live_uri = await table_ref.get_table_uri()
    storage_options = table_ref.get_storage_options()

    async def ensure_claim() -> None:
        await _ensure_claim(schema, claim_token)

    # Resume path: a prior attempt already built + validated temp and recorded the swap marker. The
    # marker's temp_uri is authoritative — it may be scoped to the attempt that built it.
    swap = schema.repartition_swap
    resuming = bool(swap and swap.get("state") == "ready")

    # The marker also records the scheme its temp table was built under, and that recording is
    # authoritative for the whole resume. The `target` passed in is reconstructed from the schema's
    # *current* settings whenever the pending marker is gone (see `_target_from_schema`), and those
    # settings still describe the pre-swap layout — saving them once temp is swapped in would write
    # the exact data/settings mismatch the marker exists to prevent.
    staged_scheme = (swap or {}).get("target") if resuming else None
    staged_target = RepartitionTarget.from_dict(staged_scheme) if staged_scheme else None
    if staged_target is not None:
        target = staged_target

    # Rewrite-resume path: a prior attempt ran out of activity budget with temp holding a prefix of
    # the table. Continue appending to that temp instead of rebuilding from row 0. A staged swap wins
    # (temp is already complete there), so only consider the checkpoint when not swap-resuming.
    rewrite_checkpoint = None if resuming else schema.repartition_rewrite
    resuming_rewrite = rewrite_checkpoint is not None

    if resuming:
        temp_uri = (swap or {}).get("temp_uri") or _temp_uri_for(live_uri, claim_token)
    elif resuming_rewrite:
        temp_uri = (rewrite_checkpoint or {}).get("temp_uri") or _temp_uri_for(live_uri, claim_token)
    else:
        temp_uri = _temp_uri_for(live_uri, claim_token)

    await ensure_claim()

    try:
        old_delta = await table_ref.get_delta_table()
    except (deltalake.exceptions.DeltaError, FileNotFoundError) as e:
        # Live's `_delta_log` is unreadable (an OOM-crashed merge or interrupted swap). If a swap was
        # already staged we can still recover from temp below; otherwise skip and let the import
        # activity's handle_corrupted_delta_log revive it — don't count this as a repartition failure.
        if not resuming:
            await logger.awarning(
                f"repartition: live table unreadable, skipping (will be revived) schema_id={schema.id}: {e}",
                schema_id=str(schema.id),
            )
            return {"outcome": "skipped", "reason": "live_unreadable"}
        old_delta = None

    if old_delta is None:
        # Live table missing. If a swap was already in progress (temp built + marker recorded), an
        # interrupted prior run may have deleted live *after* recording the marker but before copying
        # temp back. temp is the durable source of truth in that window, so resume the swap from it
        # rather than skipping — a plain skip would strand the markers forever (every later run hits
        # this same early return) and let the next sync bootstrap an empty table over the lost data.
        if resuming:
            return await _resume_swap_with_missing_live(
                table_ref=table_ref,
                schema=schema,
                target=target,
                temp_uri=temp_uri,
                live_uri=live_uri,
                storage_options=storage_options,
                logger=logger,
                ensure_claim=ensure_claim,
                claim_token=claim_token,
            )
        await logger.ainfo(f"repartition: no delta table, skipping schema_id={schema.id}", schema_id=str(schema.id))
        return {"outcome": "skipped", "reason": "no_delta_table"}

    partition_bytes = await asyncio.to_thread(measure_partition_bytes, old_delta)
    max_partition_bytes_before = max(partition_bytes.values()) if partition_bytes else 0
    total_table_bytes = sum(partition_bytes.values())
    old_row_count = await asyncio.to_thread(_table_row_count, old_delta)

    before = {
        "partition_mode": schema.partition_mode,
        "partition_format": schema.partition_format,
        "partition_count": schema.partition_count,
        "partition_size": schema.partition_size,
    }

    if resuming:
        # Validate the temp the marker points at is actually complete. An interrupted swap or cleanup can
        # leave it partial or corrupt; resuming from it would copy a broken table over live and loop
        # forever. When it's bad, discard it and fall through to a fresh rebuild — live is intact here.
        temp_rows = await _valid_delta_row_count(temp_uri, storage_options)
        if temp_rows == old_row_count:
            resolved = target
            rows_written = old_row_count
            await logger.ainfo(f"repartition: resuming from valid temp schema_id={schema.id}", schema_id=str(schema.id))
        elif staged_target is not None and await _live_matches_scheme(live_uri, storage_options, staged_target, logger):
            # temp is gone because the swap finished and deleted it — only the settings write was
            # lost. Live already carries the marker's keys, so there is nothing to rewrite: finish the
            # interrupted write instead of re-streaming the whole table for a scheme it already has.
            await ensure_claim()
            await _persist_resolved_scheme(schema, staged_target, claim_token, logger)
            table_ref.invalidate_cached_table()
            await logger.ainfo(
                f"repartition: recovered an unrecorded swap, saved scheme={_format_scheme(staged_target)} "
                f"schema_id={schema.id}",
                schema_id=str(schema.id),
            )
            return {"outcome": "completed", "row_count": old_row_count, "recovered": "scheme_only"}
        else:
            await logger.awarning(
                f"repartition: resume marker points at an invalid temp (rows={temp_rows} "
                f"expected={old_row_count}), discarding and rebuilding fresh schema_id={schema.id}",
                schema_id=str(schema.id),
            )
            await asyncio.to_thread(schema.clear_repartition_swap)
            resuming = False
            # Rebuild under our own claim-scoped temp; the stale one is swept with the orphans below.
            temp_uri = _temp_uri_for(live_uri, claim_token)

    if not resuming:
        skip_rows = 0
        copied: frozenset[str] = frozenset()
        rewrite_target = target
        if resuming_rewrite:
            # A prior attempt stopped with temp holding every row of some source files, which its
            # commits record. Resuming skips those files and copies the rest. The sync's merge runs
            # after a swallowed repartition failure, so live may have moved on since the checkpoint.
            # That only matters when the move removed a copied file or added a column (see
            # `resume_blocker`); appended files are simply copied with the rest. A temp that is
            # unreadable, larger than live, or out of step with its record is unusable: discard it
            # and rebuild fresh from the still-intact live table.
            live_version = await asyncio.to_thread(old_delta.version)
            checkpoint_version = (rewrite_checkpoint or {}).get("live_version")
            temp_rows = await _valid_delta_row_count(temp_uri, storage_options)
            recorded = await _copied_source_files(temp_uri, storage_options) if temp_rows is not None else None
            blocker: str | None
            if temp_rows is None:
                blocker = "temp_unreadable"
            elif temp_rows > old_row_count:
                blocker = "temp_larger_than_live"
            elif recorded is None:
                blocker = None
            else:
                live_sources = await asyncio.to_thread(plan_source_files, old_delta)
                blocker = await asyncio.to_thread(
                    resume_blocker,
                    live_sources=live_sources,
                    live_schema=arrow_schema_of(old_delta.schema()),
                    temp_uri=temp_uri,
                    storage_options=storage_options,
                    copied=recorded,
                    temp_rows=temp_rows,
                )
            if blocker is None and recorded is None:
                # A temp an older rewrite wrote records rows, not source files, so it cannot be
                # resumed. That says nothing about the budget, so rebuild without the give-up check.
                await logger.awarning(
                    f"repartition: rewrite checkpoint does not record its source files, rebuilding fresh "
                    f"schema_id={schema.id}",
                    schema_id=str(schema.id),
                )
                await asyncio.to_thread(schema.clear_repartition_rewrite)
                resuming_rewrite = False
                temp_uri = _temp_uri_for(live_uri, claim_token)
            elif blocker is not None:
                if _restart_would_run_out_of_budget(rewrite_checkpoint or {}, old_row_count):
                    raise RepartitionTooLargeForBudgetError(
                        f"a full activity budget covered {(rewrite_checkpoint or {}).get('rows_written')} of "
                        f"{old_row_count} rows and the checkpoint cannot be resumed, so re-streaming from row 0 "
                        f"cannot finish either (schema_id={schema.id})"
                    )
                await logger.awarning(
                    f"repartition: rewrite checkpoint is unusable reason={blocker} (temp_rows={temp_rows} "
                    f"live={old_row_count} checkpoint_version={checkpoint_version} live_version={live_version}), "
                    f"discarding and rebuilding fresh schema_id={schema.id}",
                    schema_id=str(schema.id),
                    reason=blocker,
                )
                await asyncio.to_thread(schema.clear_repartition_rewrite)
                resuming_rewrite = False
                temp_uri = _temp_uri_for(live_uri, claim_token)
            else:
                skip_rows = temp_rows or 0
                copied = recorded or frozenset()
                checkpoint_target = (rewrite_checkpoint or {}).get("target")
                if checkpoint_target:
                    # Pin the scheme the prior attempt resolved, so a resumed auto-detect can't pick a
                    # different one for the remaining rows than the ones already in temp.
                    rewrite_target = RepartitionTarget.from_dict(checkpoint_target)
                await logger.ainfo(
                    f"repartition: resuming rewrite from {skip_rows}/{old_row_count} rows already written "
                    f"schema_id={schema.id}",
                    schema_id=str(schema.id),
                )

        if not resuming_rewrite:
            # Fresh build: sweep every stale/orphaned temp variant, then stream the live table into ours.
            async with aget_s3_client(fresh_instance=True) as s3:
                await _purge_stale_temp_tables(s3, live_uri)

        async def save_checkpoint(rows_so_far: int, resolved_target: RepartitionTarget) -> None:
            # Same payload as the deadline handler below, written on committed progress instead. The
            # claim is re-checked under the row lock inside the write rather than before it: checking
            # first would leave a window where a superseded worker still saves, and that save carries
            # its whole stale `sync_type_config` — including its own `repartition_claim`, which would
            # un-fence the zombie. A checkpoint skipped because we lost the claim is correct; the new
            # claimant owns the rewrite now.
            if claim_token is None:
                return
            checkpoint_version = await asyncio.to_thread(old_delta.version)
            await asyncio.to_thread(
                save_repartition_checkpoint_if_claimed,
                schema,
                claim_token=claim_token,
                checkpoint={
                    "temp_uri": temp_uri,
                    # The field records what temp holds, but `rows_so_far` counts only the rows this
                    # call appended, so a resumed attempt has to add back the prefix it inherited.
                    # Recording the appended count alone makes the checkpoint go backwards mid-resume,
                    # and `_retrying_a_killed_attempt` then reads an advancing rewrite as a stalled one
                    # and stands its retry down until the next sync, whose merge invalidates the
                    # checkpoint and restarts the rewrite from row 0.
                    "rows_written": skip_rows + rows_so_far,
                    "target": resolved_target.to_dict(),
                    "live_version": checkpoint_version,
                    "held_at": datetime.now(UTC).isoformat(),
                },
            )

        try:
            rows_written, resolved = await _rewrite_into_temp(
                old_delta=old_delta,
                temp_uri=temp_uri,
                storage_options=storage_options,
                target=rewrite_target,
                save_checkpoint=save_checkpoint,
                budget=budget,
                logger=logger,
                ensure_claim=ensure_claim,
                deadline=deadline,
                total_rows=old_row_count,
                copied_files=copied,
                should_stop=should_stop,
            )
        except RepartitionBudgetExceededError as e:
            # Only a checkpoint this attempt could build on marks a restart. One the resume path
            # rejected was left by an attempt killed at an arbitrary point, so the ground re-covered
            # past it measures nothing. A checkpoint a full budget did produce never reaches the
            # rewrite, because `_restart_would_run_out_of_budget` gives up terminally ahead of it.
            # The classifier needs the distinction (see `_handle_budget_exceeded`).
            e.had_prior_checkpoint = resuming_rewrite
            # Checkpoint the half-built temp so the next attempt resumes instead of re-streaming from
            # row 0. Fenced on the claim inside the row lock, like the progress checkpoint above: a
            # superseded zombie writing here would restore its own claim along with the whole config.
            # Only checkpoint real forward progress.
            await ensure_claim()
            partial_rows = await _valid_delta_row_count(temp_uri, storage_options)
            if partial_rows and claim_token is not None:
                live_version = await asyncio.to_thread(old_delta.version)
                e.checkpoint_saved = await asyncio.to_thread(
                    save_repartition_checkpoint_if_claimed,
                    schema,
                    claim_token=claim_token,
                    checkpoint={
                        "temp_uri": temp_uri,
                        "rows_written": partial_rows,
                        "target": (e.resolved or rewrite_target).to_dict(),
                        # Fences the resume: only valid while live stays at this version (see the
                        # resume path). A merge that commits between attempts bumps it and invalidates.
                        "live_version": live_version,
                        # Set only here, so the rows above measure what one whole budget covers — the
                        # periodic saves record an arbitrary point instead (see
                        # `_restart_would_run_out_of_budget`).
                        "budget_exhausted": True,
                        # Stamped on every checkpoint write, so it moves forward only while the rewrite
                        # keeps advancing. The import gate reads it to decide whether this rewrite is
                        # still live enough to be worth pausing ingestion for.
                        "held_at": datetime.now(UTC).isoformat(),
                    },
                )
            raise
        except (RepartitionSupersededError, RepartitionUnpartitionableError, RepartitionStoppedError):
            raise
        except Exception as e:
            missing_path = _missing_live_object_path(e, live_uri)
            if missing_path is None or await _live_missing_data_file(live_uri, storage_options, missing_path) is None:
                raise
            # Live is hollow: its log references a data file that's gone from S3 (the terminal state
            # an interleaved or interrupted swap leaves). No repartition attempt can succeed — every
            # rewrite re-reads the same missing file — and the sync can't detect it either (its
            # incremental merges never touch the dead partition, while queries over it fail). Schedule
            # a revive: the marker makes this run's handle_corrupted_delta_log reset the table and
            # rebuild it from source, non-billable.
            await ensure_claim()
            await asyncio.to_thread(
                schema.set_delta_revive_required,
                {
                    "reason": "repartition_scan_missing_data_file",
                    "missing_path": missing_path,
                    "detected_at": datetime.now(UTC).isoformat(),
                },
            )
            await asyncio.to_thread(schema.clear_repartition_pending)
            await asyncio.to_thread(schema.clear_repartition_swap)
            await asyncio.to_thread(schema.clear_repartition_rewrite)
            await logger.awarning(
                f"repartition: live table references a missing data file, scheduling revive "
                f"schema_id={schema.id} missing={missing_path}",
                schema_id=str(schema.id),
            )
            return {"outcome": "revive_scheduled", "reason": "live_missing_data_files", "missing_path": missing_path}

        # Validate before any destructive action — temp must hold every row.
        new_row_count = await _valid_delta_row_count(temp_uri, storage_options)
        if new_row_count != old_row_count:
            raise ValueError(
                f"repartition row-count mismatch: temp={new_row_count} live={old_row_count} "
                f"(schema_id={schema.id}) — refusing to swap"
            )

        # Marker makes the swap idempotent: temp stays the source of truth until it's confirmed live.
        # It carries the resolved scheme as well, because from the moment the swap starts the schema
        # row's own settings no longer describe what is (or is about to be) on disk — the marker is
        # then the only record of the scheme a later run has to finish writing.
        await ensure_claim()
        await asyncio.to_thread(
            schema.set_repartition_swap,
            {"state": "ready", "temp_uri": temp_uri, "live_uri": live_uri, "target": resolved.to_dict()},
        )
        # temp is complete now, so the rewrite checkpoint is obsolete — the swap marker supersedes it.
        await asyncio.to_thread(schema.clear_repartition_rewrite)

    # Swap (idempotent): replace live with a server-side copy of temp, verify, then drop temp. temp
    # holds the full re-bucketed dataset, so deleting live is safe — temp is the new source of truth.
    await _swap_temp_into_live(
        temp_uri=temp_uri,
        live_uri=live_uri,
        storage_options=storage_options,
        expected_rows=old_row_count,
        ensure_claim=ensure_claim,
    )

    # The data in S3 is on the new scheme from here, so the settings, the markers and the cooldown go
    # in as one write — a half-applied mix is a table whose merges silently duplicate every row.
    await _persist_resolved_scheme(schema, resolved, claim_token, logger)

    # The cached delta-table object points at the pre-swap files; drop it so callers re-read live.
    table_ref.invalidate_cached_table()

    await logger.ainfo(
        f"repartition: completed schema_id={schema.id} rows={rows_written} "
        f"mode={before['partition_mode']}->{resolved.partition_mode} "
        f"format={before['partition_format']}->{resolved.partition_format} "
        f"count={before['partition_count']}->{resolved.partition_count} "
        f"size={before['partition_size']}->{resolved.partition_size}",
        schema_id=str(schema.id),
        rows=rows_written,
        mode=f"{before['partition_mode']}->{resolved.partition_mode}",
        format=f"{before['partition_format']}->{resolved.partition_format}",
        count=f"{before['partition_count']}->{resolved.partition_count}",
        size=f"{before['partition_size']}->{resolved.partition_size}",
    )

    return {
        "outcome": "completed",
        "row_count": rows_written,
        "max_partition_bytes_before": max_partition_bytes_before,
        "total_table_bytes": total_table_bytes,
        "partition_mode_before": before["partition_mode"],
        "partition_mode_after": resolved.partition_mode,
        "partition_format_before": before["partition_format"],
        "partition_format_after": resolved.partition_format,
        "partition_count_before": before["partition_count"],
        "partition_count_after": resolved.partition_count,
        "partition_size_before": before["partition_size"],
        "partition_size_after": resolved.partition_size,
    }


async def _resume_swap_with_missing_live(
    *,
    table_ref: DeltaTableRef,
    schema: ExternalDataSchema,
    target: RepartitionTarget,
    temp_uri: str,
    live_uri: str,
    storage_options: dict[str, str],
    logger: FilteringBoundLogger,
    ensure_claim: Callable[[], Awaitable[None]] | None = None,
    claim_token: str | None = None,
) -> dict[str, Any]:
    """Finish a swap whose live table was already deleted by an interrupted prior run.

    Entered only when the swap marker is set but live is gone — i.e. a previous run crashed inside
    `_swap_temp_into_live` after deleting live and before the copy completed. temp is the durable
    source of truth, so its own row count is the swap's expectation. If temp is *also* gone there is
    nothing left to recover (both folders lost): clear the markers and skip so the next sync rebuilds.
    """
    expected_rows = await _valid_delta_row_count(temp_uri, storage_options)
    if expected_rows is None:
        # Both live and a usable temp are gone (temp missing or its `_delta_log` is corrupt) — nothing
        # left to recover. Clear the markers and skip so the next sync rebuilds the table from source.
        await asyncio.to_thread(schema.clear_repartition_swap)
        await asyncio.to_thread(schema.clear_repartition_pending)
        await logger.ainfo(
            f"repartition: live missing and temp unrecoverable, skipping schema_id={schema.id}",
            schema_id=str(schema.id),
        )
        return {"outcome": "skipped", "reason": "no_delta_table"}

    await logger.ainfo(
        f"repartition: live missing mid-swap, resuming from temp schema_id={schema.id}", schema_id=str(schema.id)
    )

    await _swap_temp_into_live(
        temp_uri=temp_uri,
        live_uri=live_uri,
        storage_options=storage_options,
        expected_rows=expected_rows,
        ensure_claim=ensure_claim,
    )

    await _persist_resolved_scheme(schema, target, claim_token, logger)
    table_ref.invalidate_cached_table()

    await logger.ainfo(
        f"repartition: recovered from interrupted swap schema_id={schema.id} rows={expected_rows}",
        schema_id=str(schema.id),
        rows=expected_rows,
    )
    return {"outcome": "completed", "row_count": expected_rows, "recovered": True}


async def _swap_temp_into_live(
    *,
    temp_uri: str,
    live_uri: str,
    storage_options: dict[str, str],
    expected_rows: int,
    ensure_claim: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Atomically-enough replace `live_uri` with the contents of `temp_uri`.

    Crash-safe ordering: delete live → server-side copy temp → live → verify → delete temp. Until
    temp is deleted it remains the durable source of truth, so any retry simply re-runs this whole
    function (Delta uses relative paths in `_delta_log`, so a copied folder is a valid table).

    Files are copied one at a time preserving their path relative to temp — a single recursive
    `copy(prefix, prefix)` trips over directory-marker objects on S3-compatible stores.
    """
    # Never destroy live for an incomplete temp: confirm temp is a readable Delta table holding every
    # expected row before deleting live. A partial/corrupt temp (from an interrupted rewrite or swap)
    # would otherwise be copied over live and leave both broken. Raising is safe — the caller
    # re-validates temp on the next run and rebuilds fresh from the still-intact live.
    temp_rows = await _valid_delta_row_count(temp_uri, storage_options)
    if temp_rows != expected_rows:
        raise ValueError(
            f"repartition swap: refusing to swap, temp is incomplete "
            f"(rows={temp_rows} expected={expected_rows} temp_uri={temp_uri})"
        )

    # Deleting live is the point of no return — a superseded attempt must never reach it.
    if ensure_claim is not None:
        await ensure_claim()

    temp_prefix = temp_uri.replace("s3://", "").rstrip("/")
    async with aget_s3_client(fresh_instance=True) as s3:
        if await s3._exists(temp_uri):
            # Fully clear live before the copy. A leftover file from an incomplete recursive delete
            # merges into the copied `_delta_log` and inflates the row count past `expected_rows`,
            # tripping the verification below and looping the repartition forever.
            await _purge_s3_prefix(s3, live_uri)
            files = await s3._find(temp_uri)
            # Data files first, `_delta_log` last: a death mid-copy then leaves live without a
            # readable log — a state the corrupted-log revive detects and heals — instead of a
            # valid log referencing data files that never arrived.
            files = sorted(files, key=lambda f: "/_delta_log/" in f)
            for f in files:
                rel = f[len(temp_prefix) :]
                await s3._copy(f"s3://{f.lstrip('/')}", f"{live_uri}{rel}")

    # Verify the live copy is a valid Delta table with the expected row count before dropping temp.
    live_delta = await asyncio.to_thread(deltalake.DeltaTable, table_uri=live_uri, storage_options=storage_options)
    live_rows = await asyncio.to_thread(_table_row_count, live_delta)
    if live_rows != expected_rows:
        raise ValueError(f"repartition swap verification failed: live={live_rows} expected={expected_rows}")

    async with aget_s3_client(fresh_instance=True) as s3:
        await _purge_s3_prefix(s3, temp_uri)
