"""Runtime memory capacity planning for concurrent deltalite upserts on one pod.

deltalite runs as Temporal activity threads inside a single worker process: every
concurrent upsert — plus every delta-rs MERGE fallback and full-sync ``write_deltalake`` —
shares one address space and one cgroup memory limit. This governor decides, per upsert and
how large an upsert to run: it picks the per-call knobs
(``max_parallel_partitions`` / ``max_parallel_files`` / ``max_buffered_bytes`` /
``probe_concurrency``) sized to a fixed
per-upsert slice of pod memory. The slice is ``(pod limit × safety − reserve) / max_concurrent``,
so however many upserts run at once (up to the pod's ``MAX_CONCURRENT_ACTIVITIES``) their peaks sum
to less than the pod. deltalite therefore **always writes** — it never falls back to the delta-rs
MERGE for capacity, because the MERGE is the *more* memory-hungry path and falling back to it under
pressure is exactly what would OOM the pod. A source too big for its slice runs at ``mpp=1`` (the
memory floor, still far below the MERGE) and raises an ops signal, rather than falling back.

Two layers, by design:

* This governor (Python) is the **planner**. It divides the usable pod memory into equal
  per-upsert slices (one per concurrent activity) and sizes each upsert's knobs to its slice, so
  the concurrent upserts always fit. Memory for *non-deltalite* writers (full syncs, the rare
  genuine-error MERGE fallback whose RSS tracks table size, interpreter and allocator slack) is
  held back up front as ``reserve_mb``. It also reads live cgroup usage to log the actual memory
  delta against the prediction, for calibration.
* ``deltalite_core::limits`` (the ``DELTALITE_PROCESS_*`` env ceilings) is the **hard backstop**
  in Rust: process-global semaphores that cap total in-flight work regardless of what the
  governor predicted. The governor aims never to reach it; the backstop guarantees safety when a
  prediction is wrong.

The memory model (rust/deltalite ``REPORT.md`` §5.5–5.7): peak memory tracks the resident
source batch (the floor — linear in source rows, and no knob bounds it), the number of concurrent
partition workers (``max_parallel_partitions``, the memory dial) and the write buffers. The
coefficients below mirror ``rust/deltalite/python/deltalite_planner.py`` and are conservative
starting points — validate against real load and re-fit if needed (the process-global backstop
holds either way).

The coefficients were fitted on small target partitions, so they do not see the existing files a
merge rewrites. A changed row forces its whole file to be rewritten, and merges that rewrite many
existing rows grow the pod far past their prediction. So the planner also charges each partition
worker for the existing files of the partition it rewrites (``RewriteProfile``), read from the
table's add actions with no object-store request. When even one worker exceeds the slice, the
upsert reserves more than one slice, and later admissions wait (bounded) for that room.

Two knobs buy I/O overlap rather than memory: ``max_parallel_files`` (readers per partition
worker) and ``probe_concurrency`` (PK-column probes per worker). deltalite budgets every decoded
batch, probe or rewrite, against ``max_buffered_bytes``, so neither knob can push decoded bytes
past that cap. The governor keeps ``max_parallel_partitions × max_parallel_files`` under the
reader count of the largest plan the coefficients were measured on, and charges extra readers
as worker-equivalents, so a plan never predicts less memory than the measured shape it exceeds.
"""

from __future__ import annotations

import os
import time
import asyncio
import logging
import threading
import contextlib
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from django.conf import settings

import pyarrow as pa
import pyarrow.compute as pc

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    import deltalake

logger = logging.getLogger(__name__)

MB = 1024 * 1024

Mode = Literal["off", "advisory", "enforce"]

#: Fallback concurrency when nothing else declares it. The Temporal SDK's own default is 100
#: (posthog's worker wrapper uses 50); we pick the higher value so an unknown concurrency yields a
#: smaller, safer per-upsert slice rather than over-commit.
_DEFAULT_MAX_CONCURRENT = 100

#: A process's real max concurrent upserts, declared at startup via ``configure_process_concurrency``
#: (e.g. the v3 loader passes its BatchConsumer ``max_concurrency``). Set here rather than read from
#: an env var so the governor uses the loader's actual source of truth. None until declared.
_PROCESS_MAX_CONCURRENT: int | None = None

# --- Memory model coefficients (threaded process model; REPORT.md §5.6, deltalite_planner's
# ProcessCalibration) ---------------------------------------------------------------------------
#
# Production runs upserts as concurrent threads in ONE worker process. They share the interpreter,
# tokio runtime and object-store pools (paid once, covered by ``reserve_mb``) and, crucially, do not
# peak at the same instant — so the memory ONE upsert adds is far below its standalone peak. Measured
# (bench/threaded_bench.py): ~0.73 MB per MB of source, ~133 MB per concurrent partition worker, on a
# ~220 MB per-upsert base. This replaces the old single-upsert coefficients (floor 300 + 2·source +
# 250·mpp + buffer), which over-predicted ~2-3x and needlessly capped mpp — validated on prod, where
# observed per-upsert cgroup deltas were a small fraction of the single-upsert estimate.

#: Per concurrent upsert, before any partition worker or source (snapshot/log state, plan, channels).
_MARGINAL_BASE_MB = 220.0
#: Additional per concurrent upsert, per ``max_parallel_partitions`` worker.
_MARGINAL_PER_WORKER_MB = 133.0
#: Additional per concurrent upsert, per MB of that upsert's source batch.
_MARGINAL_PER_SOURCE_MB = 0.73
#: Beyond 4 partition workers the measured wall-clock gains vanish while memory keeps climbing.
_MAX_PARALLEL_PARTITIONS = 4
#: Concurrent file readers inside one partition worker, the shape the per-worker coefficient
#: was measured at (deltalite's own default).
_MEASURED_FILES_PER_WORKER = 4
#: Readers a partition worker may run once the reader ceiling below allows it. The decoded
#: survivor bytes stay under ``max_buffered_bytes`` whatever this is; what grows with it is the
#: compressed row group each open reader holds, which the ceiling bounds.
_MAX_PARALLEL_FILES = 8
#: Ceiling on ``max_parallel_partitions × max_parallel_files`` for one upsert: the reader count of
#: the largest plan the measured defaults could produce. A plan with more readers per worker
#: therefore never holds more row groups in flight than the model was fitted on.
_MAX_READERS_PER_UPSERT = _MAX_PARALLEL_PARTITIONS * _MEASURED_FILES_PER_WORKER
#: Concurrent PK-column probes per partition worker. Each probe holds a Parquet footer and one
#: decoded batch of the PK columns, and that batch takes byte-budget permits like a rewrite batch,
#: so probe memory is capped by ``max_buffered_bytes`` at any concurrency. Insert-only batches
#: into tables with many files are bound by probe round trips, and this overlaps them.
_PROBE_CONCURRENCY = 32
#: deltalite's default, kept explicit so the write is deterministic. The per-call cap on decoded
#: bytes in flight; the reader and probe knobs above scale latency overlap, not this.
_DEFAULT_BUFFERED_BYTES = 64 * MB
#: Resident bytes per stored byte of the existing files one partition worker rewrites: one
#: decoded copy (the footer ratio of decoded to stored bytes is about 1.4 on the tables that
#: overran their slot) with a little slack.
_REWRITE_MEMORY_FACTOR = 1.5
#: Ceiling on the rewrite memory charged to one partition worker. deltalite streams a partition,
#: so its working set must stop growing at some size; the largest single-partition merges seen in
#: production grew the pod by just under 4 GB. Without a ceiling, a small batch into a huge
#: unpartitioned table would reserve the whole pod.
_MAX_REWRITE_MB_PER_WORKER = 4096.0
#: How often a waiting admission checks for room.
_WAIT_POLL_S = 0.5
#: Rounding slack on the room check, so ``max_concurrent`` slice-sized reservations always fit.
_ROOM_TOLERANCE_MB = 1.0


@frozen
class RewriteProfile:
    """Stored bytes of the existing files one merge can rewrite, per touched partition."""

    #: Largest first. A touched partition with no candidate files is left out.
    partition_bytes: tuple[int, ...]
    #: Candidate files over all touched partitions.
    files: int

    @property
    def total_mb(self) -> float:
        return sum(self.partition_bytes) / MB

    def rewrite_mb(self, mpp: int) -> float:
        """Memory the rewrite adds when the ``mpp`` largest partitions run at the same time."""
        return sum(
            min(_REWRITE_MEMORY_FACTOR * size / MB, _MAX_REWRITE_MB_PER_WORKER) for size in self.partition_bytes[:mpp]
        )


def _files_that_can_match(add_actions: pa.Table, source: pa.Table, primary_keys: Sequence[str]) -> list[bool]:
    """Per file, False when its first-PK range cannot hold any key of the batch.

    String keys are not pruned: delta truncates long string stats, so a truncated max can sit below
    a key the file holds, and pruning on it would under-count the rewrite.
    """
    everything = [True] * add_actions.num_rows
    if not primary_keys or primary_keys[0] not in source.column_names:
        return everything
    pk = primary_keys[0]
    min_col, max_col = f"min.{pk}", f"max.{pk}"
    if min_col not in add_actions.column_names or max_col not in add_actions.column_names:
        return everything
    file_min, file_max = add_actions[min_col], add_actions[max_col]
    if (
        pa.types.is_string(file_min.type)
        or pa.types.is_large_string(file_min.type)
        or pa.types.is_binary(file_min.type)
    ):
        return everything
    bounds = pc.min_max(source[pk])
    low, high = bounds["min"], bounds["max"]
    if not low.is_valid or not high.is_valid:
        return everything
    try:
        disjoint = pc.or_kleene(
            pc.less(file_max, low.cast(file_max.type)), pc.greater(file_min, high.cast(file_min.type))
        )
    except (pa.ArrowInvalid, pa.ArrowNotImplementedError, pa.ArrowTypeError):
        return everything
    # A null comparison (a file with no stats for the key) proves nothing, so the file stays.
    return [d is not True for d in disjoint.to_pylist()]


def rewrite_profile(
    add_actions: pa.Table, source: pa.Table, partition_col: str | None, primary_keys: Sequence[str]
) -> RewriteProfile:
    """Upper bound on the existing files a merge of ``source`` rewrites, from the table's add actions.

    A file is a candidate when it is in a partition the batch touches and its PK range overlaps the
    batch. Each source row replaces at most one existing row, so a partition rewrites at most as
    many files as it has source rows; the largest candidates are counted.
    """
    if add_actions.num_rows == 0 or source.num_rows == 0:
        return RewriteProfile(partition_bytes=(), files=0)

    if partition_col is None:
        rows_per_partition: dict[str | None, int] = {None: source.num_rows}
        file_partitions: list[str | None] = [None] * add_actions.num_rows
    else:
        counts = pc.value_counts(source[partition_col].cast(pa.string()))
        rows_per_partition = {
            value: int(count or 0)
            for value, count in zip(counts.field("values").to_pylist(), counts.field("counts").to_pylist())
        }
        file_partitions = add_actions[f"partition.{partition_col}"].cast(pa.string()).to_pylist()

    sizes_by_partition: dict[str | None, list[int]] = defaultdict(list)
    can_match = _files_that_can_match(add_actions, source, primary_keys)
    for partition, size, candidate in zip(file_partitions, add_actions["size_bytes"].to_pylist(), can_match):
        if candidate and partition in rows_per_partition:
            sizes_by_partition[partition].append(size or 0)

    partition_bytes: list[int] = []
    files = 0
    for partition, sizes in sizes_by_partition.items():
        largest = sorted(sizes, reverse=True)[: rows_per_partition[partition]]
        files += len(largest)
        partition_bytes.append(sum(largest))
    return RewriteProfile(partition_bytes=tuple(sorted(partition_bytes, reverse=True)), files=files)


def estimate_rewrite_profile(
    table: deltalake.DeltaTable, source: pa.Table, partition_col: str | None, primary_keys: Sequence[str]
) -> RewriteProfile | None:
    """``rewrite_profile`` for a live table, or None when its add actions cannot be read."""
    try:
        add_actions = pa.table(table.get_add_actions(flatten=True))
        return rewrite_profile(add_actions, source, partition_col, primary_keys)
    except Exception as e:  # noqa: BLE001 - an estimate must never fail a write; None sizes as before
        logger.debug("deltalite governor: could not estimate the rewrite size: %s", e)
        return None


@dataclass(frozen=True)
class UpsertPlan:
    """A sizing decision for one upsert: the knobs, and the memory it is predicted to add."""

    max_parallel_partitions: int
    max_parallel_files: int
    max_buffered_bytes: int
    #: Predicted marginal peak RSS this upsert adds while running concurrently with others, in MB.
    predicted_peak_mb: float
    #: False when even a single worker exceeds the available slice.
    fits: bool
    probe_concurrency: int = _PROBE_CONCURRENCY
    #: The part of ``predicted_peak_mb`` charged for rewriting existing files, in MB.
    rewrite_mb: float = 0.0

    def as_upsert_kwargs(self) -> dict[str, int]:
        return {
            "max_parallel_partitions": self.max_parallel_partitions,
            "max_parallel_files": self.max_parallel_files,
            "max_buffered_bytes": self.max_buffered_bytes,
            "probe_concurrency": self.probe_concurrency,
        }


def _files_per_worker(mpp: int) -> int:
    """Readers per partition worker that keep the upsert under ``_MAX_READERS_PER_UPSERT``."""
    return max(1, min(_MAX_PARALLEL_FILES, _MAX_READERS_PER_UPSERT // mpp))


def _predict_marginal_mb(
    source_mb: float, mpp: int, files_per_worker: int = _MEASURED_FILES_PER_WORKER, rewrite_mb: float = 0.0
) -> float:
    """Marginal peak RSS one upsert adds while running concurrently (threaded model, REPORT §5.6).

    The per-worker coefficient was measured with ``_MEASURED_FILES_PER_WORKER`` readers, so a worker
    that runs more readers is charged as that many worker-equivalents. That over-counts (a worker's
    PK set and write buffer do not grow with its readers), which keeps the prediction conservative.
    ``rewrite_mb`` is the memory for the existing files the ``mpp`` workers rewrite at once
    (``RewriteProfile.rewrite_mb``).
    """
    worker_equivalents = mpp * files_per_worker / _MEASURED_FILES_PER_WORKER
    return (
        _MARGINAL_BASE_MB
        + _MARGINAL_PER_WORKER_MB * worker_equivalents
        + _MARGINAL_PER_SOURCE_MB * source_mb
        + rewrite_mb
    )


def size_upsert(
    available_mb: float,
    source_mb: float,
    n_partitions: int | None = None,
    rewrite: RewriteProfile | None = None,
) -> UpsertPlan:
    """Pick the largest ``max_parallel_partitions`` whose marginal peak fits ``available_mb``.

    ``available_mb`` is the per-upsert memory slice, not the whole pod. Start at the cap and step
    down. Each step gets as many readers per worker as the reader ceiling allows, so an upsert with
    few partitions overlaps more file reads without exceeding the in-flight readers of a full plan.
    When no such plan fits, try one worker at the measured reader count; if even that exceeds the
    slice, return it with ``fits=False``. The caller does not fall back on ``fits=False`` — it runs
    deltalite at ``mpp=1`` anyway (still the memory floor, far below the MERGE) and flags
    ``capacity_exceeded``. ``rewrite=None`` (sizes unknown) charges no rewrite memory.
    """
    partition_cap = _MAX_PARALLEL_PARTITIONS
    if n_partitions is not None and n_partitions >= 1:
        partition_cap = min(partition_cap, n_partitions)

    for mpp in range(partition_cap, 0, -1):
        rewrite_mb = rewrite.rewrite_mb(mpp) if rewrite is not None else 0.0
        # Partition workers come first: a plan with more workers beats one with more readers per
        # worker, so every plan the measured defaults could produce is still reachable.
        for files in sorted({_files_per_worker(mpp), _MEASURED_FILES_PER_WORKER}, reverse=True):
            predicted = _predict_marginal_mb(source_mb, mpp, files, rewrite_mb)
            if predicted <= available_mb:
                return UpsertPlan(
                    mpp, files, _DEFAULT_BUFFERED_BYTES, round(predicted, 1), fits=True, rewrite_mb=round(rewrite_mb, 1)
                )

    rewrite_mb = rewrite.rewrite_mb(1) if rewrite is not None else 0.0
    minimal = _predict_marginal_mb(source_mb, 1, rewrite_mb=rewrite_mb)
    return UpsertPlan(
        1,
        _MEASURED_FILES_PER_WORKER,
        _DEFAULT_BUFFERED_BYTES,
        round(minimal, 1),
        fits=False,
        rewrite_mb=round(rewrite_mb, 1),
    )


# --- Reading the pod's real memory (cgroup v2, with v1 and psutil fallbacks) -----------------


class PodMemory:
    """Reads the pod's memory limit and live usage from the cgroup the process runs in.

    cgroup v2 (``memory.max`` / ``memory.current``) first, then v1
    (``memory.limit_in_bytes`` / ``memory.usage_in_bytes``), then psutil for usage on hosts with
    no cgroup (local dev / macOS). The limit is read once and cached (it does not change under a
    running pod); usage is read live on every admission.
    """

    _V2_MAX = "/sys/fs/cgroup/memory.max"
    _V2_CURRENT = "/sys/fs/cgroup/memory.current"
    _V1_MAX = "/sys/fs/cgroup/memory/memory.limit_in_bytes"
    _V1_CURRENT = "/sys/fs/cgroup/memory/memory.usage_in_bytes"
    # A v1 "unlimited" limit is a sentinel near the top of the address space, not a real cap.
    _V1_UNLIMITED = 0x7FFFFFFFFFFFF000

    def __init__(self, limit_override_mb: float | None = None) -> None:
        self._limit_override_mb = limit_override_mb
        self._limit_mb: float | None = None
        self._limit_read = False

    @staticmethod
    def _read_int(path: str) -> int | None:
        try:
            with open(path) as f:
                raw = f.read().strip()
        except (OSError, ValueError):
            return None
        if raw == "max":  # cgroup v2 unlimited
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def limit_mb(self) -> float | None:
        """The pod's memory limit in MB, or None if it cannot be determined (unlimited/unreadable)."""
        if self._limit_read:
            return self._limit_mb
        self._limit_read = True
        if self._limit_override_mb is not None:
            self._limit_mb = self._limit_override_mb
            return self._limit_mb
        for path in (self._V2_MAX, self._V1_MAX):
            v = self._read_int(path)
            if v is not None and 0 < v < self._V1_UNLIMITED:
                self._limit_mb = v / MB
                return self._limit_mb
        self._limit_mb = None
        return None

    def current_mb(self) -> float | None:
        """Live memory currently used by everything in this cgroup, in MB, or None if unreadable."""
        for path in (self._V2_CURRENT, self._V1_CURRENT):
            v = self._read_int(path)
            if v is not None:
                return v / MB
        try:
            import psutil

            return psutil.Process().memory_info().rss / MB
        except Exception:  # noqa: BLE001 - no cgroup and no psutil: caller degrades to conservative mode
            return None


# --- Governor configuration ------------------------------------------------------------------


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("invalid %s=%r; using default %s", name, raw, default)
        return default


def _env_int(name: str, default: int) -> int:
    return int(_env_float(name, default))


@dataclass(frozen=True)
class GovernorConfig:
    """Runtime configuration, read from the environment so it can be tuned without a deploy.

    ``mode`` gates the rollout:
      * ``off``      — do nothing; upserts use deltalite's own defaults (today's behaviour).
      * ``advisory`` — compute and log/emit the decision, but still use deltalite defaults for the
                       actual write. Zero behaviour change; validates the model on prod.
      * ``enforce``  — apply the sized knobs. deltalite still always writes; only the knobs change.
    """

    mode: Mode = "advisory"
    #: Fraction of the pod limit deltalite planning may target; the rest is slack for allocator
    #: retention, pyarrow buffers and anything unmodelled.
    safety: float = 0.8
    #: Max upserts that can run concurrently in this process. The usable pod budget is divided by
    #: this so all ``max_concurrent`` upserts are guaranteed to fit at once — the guarantee that lets
    #: deltalite always write instead of falling back to the memory-hungry MERGE. Resolved by
    #: ``_resolve_max_concurrent`` (env override → settings.MAX_CONCURRENT_ACTIVITIES → default).
    max_concurrent: int = _DEFAULT_MAX_CONCURRENT
    #: Headroom held back from deltalite for everything else on the pod: full-refresh writes, the
    #: rare genuine-error MERGE fallback (its RSS tracks table size), interpreter and allocator slack.
    reserve_mb: float = 2048.0
    #: Used only when the cgroup limit is unreadable (local dev). None + unreadable ⇒ deltalite defaults.
    limit_override_mb: float | None = None
    #: Longest an enforce-mode admission waits for room before it writes anyway. The wait holds no
    #: reservation, so it can never block a release; the bound keeps a waiter from stalling its slot.
    max_wait_s: float = 60.0

    @staticmethod
    def from_env() -> GovernorConfig:
        mode = os.environ.get("DELTALITE_GOVERNOR_MODE", "advisory").strip().lower()
        if mode not in ("off", "advisory", "enforce"):
            logger.warning("invalid DELTALITE_GOVERNOR_MODE=%r; defaulting to advisory", mode)
            mode = "advisory"
        override = os.environ.get("DELTALITE_GOVERNOR_LIMIT_MB")
        return GovernorConfig(
            mode=mode,  # type: ignore[arg-type]
            safety=_env_float("DELTALITE_GOVERNOR_SAFETY", 0.8),
            max_concurrent=GovernorConfig._resolve_max_concurrent(),
            reserve_mb=_env_float("DELTALITE_GOVERNOR_RESERVE_MB", 2048.0),
            limit_override_mb=float(override) if override else None,
            max_wait_s=max(0.0, _env_float("DELTALITE_GOVERNOR_MAX_WAIT_S", 60.0)),
        )

    @staticmethod
    def _resolve_max_concurrent() -> int:
        """Max concurrent upserts on this process, from the same source of truth as the worker.

        Resolution order:
          1. ``DELTALITE_GOVERNOR_MAX_CONCURRENT`` env override (ops escape hatch).
          2. A value declared by the process at startup via ``configure_process_concurrency`` — the
             v3 Kafka loader passes its ``BatchConsumer.max_concurrency`` here, since it is not a
             Temporal worker and ``MAX_CONCURRENT_ACTIVITIES`` does not describe it.
          3. ``settings.MAX_CONCURRENT_ACTIVITIES`` — what the Temporal worker is configured with.
          4. ``_DEFAULT_MAX_CONCURRENT`` with a warning, so it is visible when the slice is sized
             against a guess rather than the real concurrency.
        """
        explicit = os.environ.get("DELTALITE_GOVERNOR_MAX_CONCURRENT")
        if explicit:
            return max(1, _env_int("DELTALITE_GOVERNOR_MAX_CONCURRENT", _DEFAULT_MAX_CONCURRENT))
        if _PROCESS_MAX_CONCURRENT is not None:
            return _PROCESS_MAX_CONCURRENT
        configured = getattr(settings, "MAX_CONCURRENT_ACTIVITIES", None)
        if configured:
            return max(1, int(configured))
        logger.warning(
            "deltalite governor: neither DELTALITE_GOVERNOR_MAX_CONCURRENT nor "
            "settings.MAX_CONCURRENT_ACTIVITIES is set; sizing the per-upsert memory slice against a "
            "default of %d concurrent upserts. Set one to this worker's real concurrency.",
            _DEFAULT_MAX_CONCURRENT,
        )
        return _DEFAULT_MAX_CONCURRENT


@dataclass(frozen=False)
class Admission:
    """The knobs to write one upsert with, plus diagnostics.

    There is no "decline": deltalite ALWAYS writes. The governor only decides how many partition
    workers this upsert may use, sized to a fixed per-upsert slice of pod memory so all
    ``max_concurrent`` upserts are guaranteed to fit. If a source is so big that even one worker
    exceeds its slice, ``capacity_exceeded`` is set and we still run deltalite at ``mpp=1`` (the
    memory floor, still far below the MERGE) rather than fall back to it.
    """

    upsert_kwargs: dict[str, int]
    mode: Mode
    predicted_peak_mb: float | None
    #: The per-upsert memory slice this upsert was sized against, in MB.
    budget_mb: float | None
    #: The max_parallel_partitions the governor would use — recorded in every mode (including
    #: advisory, where ``upsert_kwargs`` stays empty) so we can see the planned parallelism.
    planned_mpp: int | None = None
    #: True when even mpp=1 overflows the slice: an ops signal to chunk the source, raise the pod
    #: limit, or lower max_concurrent. Not a failure — deltalite still runs at mpp=1.
    capacity_exceeded: bool = False
    #: Filled in on release with the observed cgroup delta, for predicted-vs-actual calibration.
    observed_delta_mb: float | None = field(default=None)
    #: The part of ``predicted_peak_mb`` charged for rewriting existing files. None when sizes are unknown.
    rewrite_mb: float | None = None
    #: Stored MB of all candidate files the merge can rewrite, over every touched partition.
    rewrite_total_mb: float | None = None
    rewrite_files: int | None = None
    #: Slices this upsert holds (enforce) or would hold (advisory). Above 1 when even mpp=1 overflows.
    reserved_slots: float | None = None
    #: Time spent waiting for room before the write, and whether the wait ran out.
    wait_ms: int = 0
    wait_timed_out: bool = False


# --- The governor ----------------------------------------------------------------------------


class MemoryGovernor:
    """Process-wide admission control for deltalite upserts. Construct one per process.

    State is guarded by a ``threading.Lock``, not an ``asyncio.Lock``, on purpose: the V3 loader
    runs concurrent ``process_message`` calls in worker threads, each driving ``DeltaWriter.write``
    through ``async_to_sync`` on its own short-lived event loop. An ``asyncio.Lock`` binds to the
    first loop that touches it and is not thread-safe, so a governor singleton shared across those
    per-thread loops would error or race. The critical sections here are tiny and fully synchronous
    (a few arithmetic ops, no ``await`` inside, and the lock is never held across the ``yield``), so
    a plain thread lock is both correct across loops and effectively uncontended.
    """

    def __init__(
        self,
        config: GovernorConfig | None = None,
        pod: PodMemory | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.config = config or GovernorConfig.from_env()
        self.pod = pod or PodMemory(limit_override_mb=self.config.limit_override_mb)
        self._lock = threading.Lock()
        self._reserved_mb = 0.0
        self._inflight = 0
        self._clock = clock
        self._sleep = sleep
        #: Tickets of admissions waiting for room, oldest first.
        self._waiters: deque[int] = deque()
        self._next_ticket = 0

    # -- accounting --------------------------------------------------------------------------

    def _per_upsert_budget_mb(self, limit_mb: float) -> float:
        """The fixed memory slice one upsert may size itself to.

        ``(usable pod memory) / max_concurrent`` — so however many upserts run at once (up to
        ``max_concurrent``), the sum of their sized peaks stays under the pod. This static division
        is the capacity guarantee that lets deltalite always write without ever falling back to the
        memory-hungry MERGE for capacity reasons.
        """
        usable = limit_mb * self.config.safety - self.config.reserve_mb
        return max(0.0, usable) / self.config.max_concurrent

    def slot_budget_mb(self) -> float | None:
        """The memory slice one load slot may use, or None when the pod's limit is unreadable."""
        limit_mb = self.pod.limit_mb()
        return None if limit_mb is None else self._per_upsert_budget_mb(limit_mb)

    def _has_room(self, reserve_mb: float, usable_mb: float) -> bool:
        return self._reserved_mb + reserve_mb <= usable_mb + _ROOM_TOLERANCE_MB

    def _take(self, reserve_mb: float) -> None:
        self._reserved_mb += reserve_mb
        self._inflight += 1

    async def _reserve(self, reserve_mb: float, usable_mb: float) -> tuple[float, bool]:
        """Reserve ``reserve_mb`` once it fits the pod, oldest waiter first. Returns (waited_s, timed_out).

        While every upsert reserves at most one slice, ``max_concurrent`` of them always fit and
        nothing waits. Only an over-slice reservation can make the pod full. Then newcomers queue
        behind the oldest waiter rather than pile on, so the big upsert is not starved by small ones.
        A waiter holds no reservation, and a reservation is released whatever happens to its
        upsert, so a wait can only end. After ``max_wait_s`` the upsert reserves anyway and
        writes, because deltalite must always write.
        """
        with self._lock:
            if not self._waiters and self._has_room(reserve_mb, usable_mb):
                self._take(reserve_mb)
                return 0.0, False
            ticket = self._next_ticket
            self._next_ticket += 1
            self._waiters.append(ticket)
        started = self._clock()
        reserved = False
        try:
            while True:
                await self._sleep(_WAIT_POLL_S)
                with self._lock:
                    now = self._clock()
                    room = self._waiters[0] == ticket and self._has_room(reserve_mb, usable_mb)
                    if room or now - started >= self.config.max_wait_s:
                        self._waiters.remove(ticket)
                        self._take(reserve_mb)
                        reserved = True
                        return now - started, not room
        finally:
            if not reserved:
                # Cancelled while it waited: give up the place in the queue.
                with self._lock:
                    if ticket in self._waiters:
                        self._waiters.remove(ticket)

    @contextlib.asynccontextmanager
    async def admit(
        self,
        *,
        source_bytes: int,
        n_partitions: int | None = None,
        rewrite: RewriteProfile | None = None,
    ) -> AsyncIterator[Admission]:
        """Size one upsert to its memory slice and yield the knobs to run it with.

        Use as ``async with governor.admit(...) as adm``. deltalite always writes — the reservation
        is held for the whole ``with`` block and released on exit, even on exception. In enforce
        mode an upsert predicted above its slice reserves up to the whole usable pod, and entry
        waits (bounded by ``max_wait_s``) until the reservation fits beside the ones in flight.
        """
        source_mb = source_bytes / MB

        if self.config.mode == "off":
            yield Admission({}, "off", None, None)
            return

        limit_mb = self.pod.limit_mb()
        # No cgroup limit visible (local dev / unreadable): we can't size a slice, so use deltalite's
        # own defaults. Still always deltalite.
        if limit_mb is None:
            yield Admission({}, self.config.mode, None, None)
            return

        budget_mb = self._per_upsert_budget_mb(limit_mb)
        usable_mb = budget_mb * self.config.max_concurrent
        plan = size_upsert(budget_mb, source_mb, n_partitions, rewrite)
        # Capped at the usable pod so an upsert alone always fits and never waits for itself.
        reserve_mb = min(plan.predicted_peak_mb, usable_mb)

        # Only enforce reserves against the budget (and may wait for room); advisory is a pure
        # no-op on the accounting.
        admitted = False
        waited_s, timed_out = 0.0, False
        if self.config.mode == "enforce":
            waited_s, timed_out = await self._reserve(reserve_mb, usable_mb)
            admitted = True
        # Read live usage after any wait, in every mode, so the observed cgroup delta covers the
        # write itself — the calibration advisory mode exists for.
        current_at_admit = self.pod.current_mb()

        adm = Admission(
            upsert_kwargs=plan.as_upsert_kwargs() if admitted else {},
            mode=self.config.mode,
            predicted_peak_mb=plan.predicted_peak_mb,
            budget_mb=round(budget_mb, 1),
            planned_mpp=plan.max_parallel_partitions,
            capacity_exceeded=not plan.fits,
            rewrite_mb=plan.rewrite_mb if rewrite is not None else None,
            rewrite_total_mb=round(rewrite.total_mb, 1) if rewrite is not None else None,
            rewrite_files=rewrite.files if rewrite is not None else None,
            reserved_slots=round(reserve_mb / budget_mb, 2) if budget_mb > 0 else None,
            wait_ms=round(waited_s * 1000),
            wait_timed_out=timed_out,
        )
        self._emit_decision(adm, source_mb)
        try:
            yield adm
        finally:
            if admitted:
                with self._lock:
                    self._reserved_mb -= reserve_mb
                    self._inflight -= 1
            # Best-effort predicted-vs-actual, all modes (whole-process delta, so noisy under load).
            if current_at_admit is not None:
                now = self.pod.current_mb()
                if now is not None:
                    adm.observed_delta_mb = round(now - current_at_admit, 1)

    # -- observability -----------------------------------------------------------------------

    def _emit_decision(self, adm: Admission, source_mb: float) -> None:
        """Log the decision and emit metrics. Never raises into the write path."""
        if adm.capacity_exceeded:
            logger.warning(
                "deltalite governor: source %.0f MB with %.0f MB of rewrite memory exceeds its "
                "%.0f MB per-upsert slice (max_concurrent=%d); running deltalite at mpp=1 and "
                "reserving %.2f slices (waited %d ms, timed out: %s).",
                source_mb,
                adm.rewrite_mb or 0.0,
                adm.budget_mb or 0.0,
                self.config.max_concurrent,
                adm.reserved_slots or 0.0,
                adm.wait_ms,
                adm.wait_timed_out,
            )
        try:
            from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.metrics import (
                DELTALITE_GOVERNOR_DECISION_TOTAL,
                DELTALITE_GOVERNOR_INFLIGHT,
                DELTALITE_GOVERNOR_PREDICTED_PEAK_MB,
                DELTALITE_GOVERNOR_RESERVED_MB,
            )

            outcome = "capacity_exceeded" if adm.capacity_exceeded else "admitted"
            DELTALITE_GOVERNOR_DECISION_TOTAL.labels(mode=adm.mode, outcome=outcome).inc()
            DELTALITE_GOVERNOR_INFLIGHT.set(self._inflight)
            DELTALITE_GOVERNOR_RESERVED_MB.set(self._reserved_mb)
            if adm.predicted_peak_mb is not None:
                DELTALITE_GOVERNOR_PREDICTED_PEAK_MB.observe(adm.predicted_peak_mb)
        except Exception:  # noqa: BLE001 - metrics are best-effort; never fail a write over them
            pass


_GOVERNOR: MemoryGovernor | None = None


def configure_process_concurrency(max_concurrent: int) -> None:
    """Declare this process's real max concurrent upserts, from its own source of truth.

    The v3 loader calls this with its ``BatchConsumer.max_concurrency`` at startup, before the first
    upsert, so the governor sizes each memory slice against the loader's actual concurrency instead
    of the Temporal-only ``MAX_CONCURRENT_ACTIVITIES`` (unset there) or a conservative default. Takes
    precedence over the setting; the ``DELTALITE_GOVERNOR_MAX_CONCURRENT`` env override still wins.
    Resets the singleton so the next ``get_governor()`` rebuilds with the declared value.
    """
    global _PROCESS_MAX_CONCURRENT, _GOVERNOR
    _PROCESS_MAX_CONCURRENT = max(1, int(max_concurrent))
    _GOVERNOR = None


def get_governor() -> MemoryGovernor:
    """The process-wide governor singleton, built lazily from the environment on first use."""
    global _GOVERNOR
    if _GOVERNOR is None:
        _GOVERNOR = MemoryGovernor()
    return _GOVERNOR


def reset_governor_for_tests(governor: MemoryGovernor | None = None) -> None:
    """Swap the process singleton — tests only."""
    global _GOVERNOR
    _GOVERNOR = governor
