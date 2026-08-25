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
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import deltalake as deltalake
import deltalake.exceptions
from structlog.types import FilteringBoundLogger

from posthog.temporal.common.utils import retry_on_db_connection_drop

from products.data_warehouse.backend.facade.api import aget_s3_client
from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    save_repartition_checkpoint_if_claimed,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    evolve_pyarrow_schema,
    normalize_column_name,
    realign_decimal_buffers,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.batcher import DEFAULT_MAX_TABLE_BYTES
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import _purge_s3_prefix
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.partitioning import (
    NULL_NUMERICAL_PARTITION,
    append_partition_key_to_table,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.table_stats import table_payload_bytes
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

# Rows per scanned record-batch. A row count cannot bound memory on its own — the same count is a few
# MB of a narrow table and gigabytes of nested records — so this is deliberately low rather than
# tuned, the way `MAX_FETCH_PAGE_ROWS` is in `sources/common/sql/batching.py`. It bounds the window
# that is still unmeasured when the scan hands a batch over; `REWRITE_BUFFER_MAX_BYTES` bounds what
# is materialised, from real measurements. Low is cheap here: the parquet row group is read either
# way, and the coalescing buffer merges small batches back before any commit.
DEFAULT_REPARTITION_BATCH_SIZE = 1_000

# Minimum gap between claim re-reads during the rewrite loop. The loop yields at least one batch per
# source *file*, so an over-fragmented table (the exact kind being repartitioned) produces one batch
# per partition regardless of `DEFAULT_REPARTITION_BATCH_SIZE` — a few thousand rows spread over a few
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
# interval rather than to the whole rewrite.
CHECKPOINT_INTERVAL_SECONDS = 30.0

# Arrow payload the rewrite may hold in its coalescing buffer. Half the package's per-table cap
# deliberately: the batch that triggers a flush is already materialised and stays resident while the
# buffer drains, so the true peak is buffer + one incoming batch. Budgeting half keeps that sum inside
# one `DEFAULT_MAX_TABLE_BYTES` instead of letting it reach twice the cap. Coalescing loses nothing
# that matters — the win comes from merging thousands of KB-sized batches, not from filling the cap.
REWRITE_BUFFER_MAX_BYTES = DEFAULT_MAX_TABLE_BYTES // 2

# Rows the coalescing buffer may hold before it commits. Deliberately not the scan batch size: one
# number for both caps the buffer at a single batch, so nothing coalesces and every batch becomes its
# own Delta commit. Each commit is a transaction-log write, so that puts a floor under throughput that
# no table large enough to need repartitioning can finish above.
REWRITE_BUFFER_MAX_ROWS = 50_000

# Arrow's default 16-batch readahead keeps memory in flight that never reaches the coalescing buffer,
# so no buffer budget bounds it. Fragment readahead is left at its default: serialising file reads
# would cost the most on the many-small-files tables this module rewrites.
REWRITE_BATCH_READAHEAD = 1

TEMP_URI_SUFFIX = "__repartitioned"


class RepartitionUnpartitionableError(Exception):
    """The table has no column suitable for partitioning — repartition is skipped, not retried."""


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
    inherit nothing. `had_prior_checkpoint` splits them: True means a checkpoint existed at the start of
    this attempt (so re-covering ground from row 0 is a restart, not progress), False means there was
    none to inherit. `checkpoint_saved` records whether this attempt persisted a checkpoint the next run
    can resume from. A fresh first attempt that saved one is forward progress; the caller sets both.
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

    Each attempt is charged before the rewrite runs and refunded on a clean stand-down (supersession,
    cancellation, transient infra), so reaching the cap this way means every attempt was hard-killed
    mid-run — worker OOM, activity timeout, or an eviction that didn't surface as a cancellation —
    before it could fail cleanly or checkpoint progress. Terminal, and unlike a caught failure it
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


def measure_partition_bytes(delta_table: deltalake.DeltaTable) -> dict[str | None, int]:
    """At-rest bytes per partition, read from the Delta log (no S3 LIST, no data scan).

    Unpartitioned tables collapse to a single `None` bucket. Keyed by the `_ph_partition_key` value.
    """
    actions = delta_table.get_add_actions(flatten=True)
    columns = actions.schema.names
    sizes = actions.column("size_bytes").to_pylist()

    partition_column = f"partition.{PARTITION_KEY}"
    keys: list[str | None]
    if partition_column in columns:
        keys = list(actions.column(partition_column).to_pylist())
    else:
        keys = [None] * len(sizes)

    totals: dict[str | None, int] = defaultdict(int)
    for key, size in zip(keys, sizes):
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
    `datetime_at_finest_tier`, `numerical_cannot_shrink`, `numerical_no_size`, or
    `unpartitionable_no_keys`. A chosen target carries reason `selected`.
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
            # Already at the finest usable tier — can't go finer. Caller alerts.
            return None, "datetime_at_finest_tier"
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
# That one is sized by upper bound instead (see `_simulate_datetime_coarsening`) rather than left
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


def _simulate_datetime_coarsening(
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
            if acceptable(_simulate_datetime_coarsening(partition_bytes, current_format, new_format)):
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


def _read_next_batch(reader: pa.RecordBatchReader) -> pa.RecordBatch | None:
    try:
        return reader.read_next_batch()
    except StopIteration:
        return None


def _format_scheme(target: RepartitionTarget) -> str:
    """`datetime/month`, `md5/64`, `numerical/1000000` — the scheme in one readable token."""
    knob = target.partition_format or target.partition_count or target.partition_size
    return f"{target.partition_mode or 'auto'}/{knob}" if knob else (target.partition_mode or "auto")


def _format_fields(fields: dict[str, Any]) -> str:
    return " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)


async def _rewrite_into_temp(
    *,
    old_delta: deltalake.DeltaTable,
    temp_uri: str,
    storage_options: dict[str, str],
    target: RepartitionTarget,
    batch_size: int,
    logger: FilteringBoundLogger,
    ensure_claim: Callable[[], Awaitable[None]] | None = None,
    claim_recheck_interval_seconds: float = CLAIM_RECHECK_INTERVAL_SECONDS,
    save_checkpoint: Callable[[int, RepartitionTarget], Awaitable[None]] | None = None,
    checkpoint_interval_seconds: float = CHECKPOINT_INTERVAL_SECONDS,
    deadline: float | None = None,
    total_rows: int | None = None,
    skip_rows: int = 0,
) -> tuple[int, RepartitionTarget]:
    """Stream the live table into a temp table under the new partition scheme.

    Returns (rows_written, resolved_target) — `rows_written` counts only the rows written by *this*
    call. The first processed batch resolves any auto-detected mode/format/keys so every subsequent
    batch is bucketed identically (a per-batch auto-detect could disagree). `ensure_claim` runs before
    the first batch and then at most once per `claim_recheck_interval_seconds`, so a superseded attempt
    stops within that window rather than paying a database round-trip per batch (see
    `CLAIM_RECHECK_INTERVAL_SECONDS`).

    `deadline` is a `time.monotonic()` value past which the rewrite gives up with
    `RepartitionBudgetExceededError` rather than run until Temporal kills it. None runs unbounded.

    `total_rows` is the source row count, used only to report progress as a percentage and an ETA.

    `skip_rows` resumes a prior attempt that ran out of budget: temp already holds a scan-ordered
    prefix of `skip_rows` rows, so this call reads-and-discards that many source rows (the source is
    immutable during the rewrite, so the scan order is stable) and appends only the remainder. The
    rewrite writes in `append` mode, so resuming builds on the existing temp rather than replacing it.
    """
    await logger.ainfo(
        f"repartition: rewrite starting target_scheme={_format_scheme(target)} total_rows={total_rows} "
        f"batch_size={batch_size} temp_uri={temp_uri}",
        target_scheme=_format_scheme(target),
        total_rows=total_rows,
        batch_size=batch_size,
        temp_uri=temp_uri,
    )

    dataset = await asyncio.to_thread(old_delta.to_pyarrow_dataset)
    reader = await asyncio.to_thread(
        lambda: dataset.scanner(
            batch_size=batch_size,
            batch_readahead=REWRITE_BATCH_READAHEAD,
        ).to_reader()
    )
    live_schema = await asyncio.to_thread(old_delta.schema)

    resolved: RepartitionTarget | None = None
    rows_written = 0

    buffered: list[pa.Table] = []
    buffered_rows = 0
    buffered_bytes = 0

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

    async def maybe_checkpoint() -> None:
        """Persist resumable progress, at most once per `checkpoint_interval_seconds`.

        Called after a commit lands, so the recorded row count is always backed by data actually in
        temp. Failing to checkpoint must not fail the rewrite: the attempt is still making progress,
        and the next one simply resumes from further back.
        """
        nonlocal last_checkpoint_at
        if save_checkpoint is None:
            return
        now = time.monotonic()
        if last_checkpoint_at is not None and now - last_checkpoint_at < checkpoint_interval_seconds:
            return
        last_checkpoint_at = now
        try:
            await save_checkpoint(rows_written, resolved or target)
        except RepartitionSupersededError:
            raise
        except Exception:
            await logger.awarning("repartition: could not save rewrite checkpoint", exc_info=True)

    async def flush() -> None:
        """Write the buffered batches as one Delta commit, then report progress."""
        nonlocal buffered, buffered_rows, buffered_bytes, rows_written, commits
        if not buffered:
            return
        # Every buffered table was already aligned to `live_schema`, so they concat without promotion.
        combined = buffered[0] if len(buffered) == 1 else pa.concat_tables(buffered)
        buffered = []
        buffered_rows = 0
        buffered_bytes = 0
        await asyncio.to_thread(
            deltalake.write_deltalake,
            temp_uri,
            combined,
            partition_by=PARTITION_KEY,
            mode="append",
            schema_mode="merge",
            storage_options=storage_options,
        )
        rows_written += combined.num_rows
        commits += 1
        report_buffer_bytes(0)
        await maybe_checkpoint()
        fields = progress()
        await logger.ainfo(f"repartition: rewrite progress {_format_fields(fields)}", **fields)

    last_claim_check: float | None = None
    source_rows_read = 0

    while True:
        if ensure_claim is not None:
            now = time.monotonic()
            if last_claim_check is None or now - last_claim_check >= claim_recheck_interval_seconds:
                await ensure_claim()
                last_claim_check = now
        batch = await asyncio.to_thread(_read_next_batch, reader)
        if batch is None:
            break
        # Deliberately after the read, so exhausting the reader always beats the deadline. Checking
        # first would let a rewrite that has already copied every row be discarded and charged an
        # attempt because it happened to cross the deadline on the iteration that would have hit
        # EOF, which is likeliest for a table whose rewrite lands near the budget: exactly the ones
        # this deadline exists to rescue.
        if deadline is not None and time.monotonic() >= deadline:
            raise RepartitionBudgetExceededError(
                f"rewrite exceeded its activity budget after {rows_written} rows written to {temp_uri}",
                rows_written=rows_written,
                resolved=resolved,
                resumed_from=skip_rows,
            )

        # Resume: temp already holds the first `skip_rows` rows in scan order, so read past them and
        # only append the remainder. The boundary batch is sliced so no row is written twice or lost.
        if source_rows_read < skip_rows:
            to_skip = min(batch.num_rows, skip_rows - source_rows_read)
            source_rows_read += batch.num_rows
            if to_skip == batch.num_rows:
                continue
            batch = batch.slice(to_skip)
        else:
            source_rows_read += batch.num_rows

        table = pa.Table.from_batches([batch])
        if table.num_rows == 0:
            continue
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

        partitioned_table = result.table
        if resolved is None:
            resolved = dataclasses.replace(
                target,
                partition_mode=result.partition_mode,
                partition_format=result.partition_format,
                partition_keys=result.partition_keys,
            )

        # Align each batch against the live table's own declared schema before writing. Without
        # this, whichever batch happens to build temp's schema on the first write fixes its
        # nullability from what that one batch's data looked like. So if a column the live schema
        # already declares non-nullable slips through with a real null (e.g. a source NOT NULL
        # constraint later relaxed upstream), the write aborts with "declared as non-nullable but
        # contains null values" partway through the rewrite. Every other Delta write path in this
        # pipeline runs incoming data through this same alignment first, so the rewrite must too.
        partitioned_table = evolve_pyarrow_schema(partitioned_table, live_schema)
        partitioned_table = realign_decimal_buffers(partitioned_table)

        # Coalesce before writing, so commits scale with data size rather than source file count
        # (see `CLAIM_RECHECK_INTERVAL_SECONDS`). Bound the buffer by bytes as well as rows: a row
        # count says nothing about width once `evolve_pyarrow_schema` has flattened struct and list
        # columns into JSON strings. Flush *before* appending whatever would overflow, never after,
        # or a nearly-full buffer could still take a further full-sized batch. Peak residency is this
        # buffer plus the batch in hand, which `REWRITE_BUFFER_MAX_BYTES` budgets for.
        table_bytes = table_payload_bytes(partitioned_table)
        if buffered and (
            buffered_rows + partitioned_table.num_rows > REWRITE_BUFFER_MAX_ROWS
            or buffered_bytes + table_bytes > REWRITE_BUFFER_MAX_BYTES
        ):
            await flush()
        buffered.append(partitioned_table)
        buffered_rows += partitioned_table.num_rows
        buffered_bytes += table_bytes
        # Feeds the workload reporter bound by the repartition activity; no-op everywhere else.
        report_buffer_bytes(buffered_bytes)

    await flush()

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


async def repartition_table_in_place(
    table_ref: DeltaTableRef,
    schema: ExternalDataSchema,
    target: RepartitionTarget,
    logger: FilteringBoundLogger,
    *,
    batch_size: int = DEFAULT_REPARTITION_BATCH_SIZE,
    claim_token: str | None = None,
    deadline: float | None = None,
) -> dict[str, Any]:
    """Rewrite the schema's Delta table under `target`'s finer partition scheme, in place, from S3.

    Memory is bounded by `batch_size`; the source is never re-read. Crash-safe via the
    `repartition_swap` marker (resume re-drives the swap from the intact temp table). On success,
    persists the new partition settings and clears the controller markers. Returns a stats dict for
    observability. Raises `RepartitionUnpartitionableError` (terminal) if no partition mode applies.

    `claim_token` fences out zombie attempts: the temp table is scoped to the token so concurrent
    writers can never share one, and the claim is re-checked before every destructive step — and,
    during the rewrite, at most once per `CLAIM_RECHECK_INTERVAL_SECONDS` (raising
    `RepartitionSupersededError` when a newer attempt has taken over).

    `deadline` (a `time.monotonic()` value) bounds the rewrite phase only. The swap that follows
    needs no bound of its own: it records `repartition_swap` before touching live, so a swap cut
    short by the activity timeout resumes from the intact temp table on a later run.
    """
    live_uri = await table_ref.get_table_uri()
    storage_options = table_ref.get_storage_options()

    async def ensure_claim() -> None:
        await _ensure_claim(schema, claim_token)

    # Resume path: a prior attempt already built + validated temp and recorded the swap marker. The
    # marker's temp_uri is authoritative — it may be scoped to the attempt that built it.
    swap = schema.repartition_swap
    resuming = bool(swap and swap.get("state") == "ready")

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
        rewrite_target = target
        if resuming_rewrite:
            # A prior attempt ran out of budget with temp holding a scan-ordered prefix of the table.
            # Resuming skips that prefix and appends the rest, which is only correct while live is
            # byte-identical to when the checkpoint was written: the sync's merge runs after a
            # swallowed repartition failure, so on any run where that merge committed, live has grown
            # and the recorded prefix no longer lines up with the current scan. The Delta version is
            # the fence — equal means no commit has touched live since, so the prefix still holds.
            # A checkpoint whose temp is unreadable, larger than live, or built against a different
            # live version is unusable: discard it and rebuild fresh from the still-intact live table.
            live_version = await asyncio.to_thread(old_delta.version)
            checkpoint_version = (rewrite_checkpoint or {}).get("live_version")
            temp_rows = await _valid_delta_row_count(temp_uri, storage_options)
            if temp_rows is None or temp_rows > old_row_count or checkpoint_version != live_version:
                await logger.awarning(
                    f"repartition: rewrite checkpoint is unusable (temp_rows={temp_rows} live={old_row_count} "
                    f"checkpoint_version={checkpoint_version} live_version={live_version}), discarding and "
                    f"rebuilding fresh schema_id={schema.id}",
                    schema_id=str(schema.id),
                )
                await asyncio.to_thread(schema.clear_repartition_rewrite)
                resuming_rewrite = False
                temp_uri = _temp_uri_for(live_uri, claim_token)
            else:
                skip_rows = temp_rows
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
                    "rows_written": rows_so_far,
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
                batch_size=batch_size,
                logger=logger,
                ensure_claim=ensure_claim,
                deadline=deadline,
                total_rows=old_row_count,
                skip_rows=skip_rows,
            )
        except RepartitionBudgetExceededError as e:
            # A checkpoint present at the start of this attempt means a resumed_from==0 restart
            # re-covered ground rather than progressing; its absence means this is a genuine first
            # attempt. The classifier needs the distinction (see `_handle_budget_exceeded`).
            e.had_prior_checkpoint = rewrite_checkpoint is not None
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
                        # Stamped on every checkpoint write, so it moves forward only while the rewrite
                        # keeps advancing. The import gate reads it to decide whether this rewrite is
                        # still live enough to be worth pausing ingestion for.
                        "held_at": datetime.now(UTC).isoformat(),
                    },
                )
            raise
        except (RepartitionSupersededError, RepartitionUnpartitionableError):
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
        await ensure_claim()
        await asyncio.to_thread(
            schema.set_repartition_swap, {"state": "ready", "temp_uri": temp_uri, "live_uri": live_uri}
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

    # Persist the new scheme and clear controller state. set_partitioning_enabled saves + pops overrides.
    await asyncio.to_thread(
        schema.set_partitioning_enabled,
        resolved.partition_keys,
        resolved.partition_count,
        resolved.partition_size,
        resolved.partition_mode,
        resolved.partition_format,
    )
    await asyncio.to_thread(schema.clear_repartition_swap)
    await asyncio.to_thread(schema.clear_repartition_pending)
    await asyncio.to_thread(schema.stamp_last_repartition_at)

    # The cached delta-table object points at the pre-swap files; drop it so callers re-read live.
    table_ref.get_delta_table.cache_clear()

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

    await asyncio.to_thread(
        schema.set_partitioning_enabled,
        target.partition_keys,
        target.partition_count,
        target.partition_size,
        target.partition_mode,
        target.partition_format,
    )
    await asyncio.to_thread(schema.clear_repartition_swap)
    await asyncio.to_thread(schema.clear_repartition_pending)
    await asyncio.to_thread(schema.stamp_last_repartition_at)
    table_ref.get_delta_table.cache_clear()

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
