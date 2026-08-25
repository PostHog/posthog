"""Runtime memory capacity planning for concurrent deltalite upserts on one pod.

deltalite runs as Temporal activity threads inside a single worker process: every
concurrent upsert — plus every delta-rs MERGE fallback and full-sync ``write_deltalake`` —
shares one address space and one cgroup memory limit. This governor decides, per upsert and
how large an upsert to run: it picks the per-call knobs
(``max_parallel_partitions`` / ``max_parallel_files`` / ``max_buffered_bytes``) sized to a fixed
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

The memory model (rust/deltalite ``REPORT.md`` §5.5–5.7): peak memory does **not** track the
target table size. It tracks the resident source batch (the floor — linear in source rows, and
no knob bounds it), the number of concurrent partition workers (``max_parallel_partitions``, the
memory dial) and the write buffers. So the only inputs that matter for sizing are the source
batch size and how many partition workers we permit. The coefficients below mirror
``rust/deltalite/python/deltalite_planner.py`` and are conservative starting points — validate
against real load and re-fit if needed (the process-global backstop holds either way).
"""

from __future__ import annotations

import os
import logging
import threading
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

from django.conf import settings

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
#: Per-call knobs the governor does not tune (mpp is the memory dial): deltalite's defaults, kept
#: explicit so the write is deterministic.
_MAX_PARALLEL_FILES = 4
_DEFAULT_BUFFERED_BYTES = 64 * MB


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

    def as_upsert_kwargs(self) -> dict[str, int]:
        return {
            "max_parallel_partitions": self.max_parallel_partitions,
            "max_parallel_files": self.max_parallel_files,
            "max_buffered_bytes": self.max_buffered_bytes,
        }


def _predict_marginal_mb(source_mb: float, mpp: int) -> float:
    """Marginal peak RSS one upsert adds while running concurrently (threaded model, REPORT §5.6)."""
    return _MARGINAL_BASE_MB + _MARGINAL_PER_WORKER_MB * mpp + _MARGINAL_PER_SOURCE_MB * source_mb


def size_upsert(available_mb: float, source_mb: float, n_partitions: int | None = None) -> UpsertPlan:
    """Pick the largest ``max_parallel_partitions`` whose marginal peak fits ``available_mb``.

    ``available_mb`` is the per-upsert memory slice, not the whole pod. Start at the cap and step
    down. If even a single worker exceeds the slice, return ``mpp=1`` with ``fits=False``. The caller
    does not fall back on ``fits=False`` — it runs deltalite at ``mpp=1`` anyway (still the memory
    floor, far below the MERGE) and flags ``capacity_exceeded``. mpp is the memory dial; the other
    knobs stay at deltalite's defaults.
    """
    partition_cap = _MAX_PARALLEL_PARTITIONS
    if n_partitions is not None and n_partitions >= 1:
        partition_cap = min(partition_cap, n_partitions)

    for mpp in range(partition_cap, 0, -1):
        predicted = _predict_marginal_mb(source_mb, mpp)
        if predicted <= available_mb:
            return UpsertPlan(mpp, _MAX_PARALLEL_FILES, _DEFAULT_BUFFERED_BYTES, round(predicted, 1), fits=True)

    minimal = _predict_marginal_mb(source_mb, 1)
    return UpsertPlan(1, _MAX_PARALLEL_FILES, _DEFAULT_BUFFERED_BYTES, round(minimal, 1), fits=False)


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


@dataclass
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

    def __init__(self, config: GovernorConfig | None = None, pod: PodMemory | None = None) -> None:
        self.config = config or GovernorConfig.from_env()
        self.pod = pod or PodMemory(limit_override_mb=self.config.limit_override_mb)
        self._lock = threading.Lock()
        self._reserved_mb = 0.0
        self._inflight = 0

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

    @contextlib.asynccontextmanager
    async def admit(self, *, source_bytes: int, n_partitions: int | None = None) -> AsyncIterator[Admission]:
        """Size one upsert to its memory slice and yield the knobs to run it with.

        Use as ``async with governor.admit(...) as adm``. deltalite always writes — the reservation
        (for observability + oversubscription accounting) is held for the whole ``with`` block and
        released on exit, even on exception.
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
        plan = size_upsert(budget_mb, source_mb, n_partitions)

        # Read live usage now, in every mode, so the observed cgroup delta over the upsert can be
        # logged against the prediction — the calibration advisory mode exists for. Only enforce
        # reserves against the budget; advisory is a pure no-op on the accounting.
        current_at_admit = self.pod.current_mb()
        admitted = False
        if self.config.mode == "enforce":
            with self._lock:
                self._reserved_mb += plan.predicted_peak_mb
                self._inflight += 1
                admitted = True

        adm = Admission(
            upsert_kwargs=plan.as_upsert_kwargs() if admitted else {},
            mode=self.config.mode,
            predicted_peak_mb=plan.predicted_peak_mb,
            budget_mb=round(budget_mb, 1),
            planned_mpp=plan.max_parallel_partitions,
            capacity_exceeded=not plan.fits,
        )
        self._emit_decision(adm, source_mb)
        try:
            yield adm
        finally:
            if admitted:
                with self._lock:
                    self._reserved_mb -= plan.predicted_peak_mb
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
                "deltalite governor: source %.0f MB exceeds its %.0f MB per-upsert slice "
                "(max_concurrent=%d); running deltalite at mpp=1. Chunk the source, raise the pod "
                "memory limit, or lower max_concurrent.",
                source_mb,
                adm.budget_mb or 0.0,
                self.config.max_concurrent,
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
