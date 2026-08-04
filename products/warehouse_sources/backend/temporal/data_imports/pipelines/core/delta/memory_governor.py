"""Runtime memory capacity planning for concurrent deltalite upserts on one pod.

deltalite runs as Temporal activity threads inside a single worker process: every
concurrent upsert — plus every delta-rs MERGE fallback and full-sync ``write_deltalake`` —
shares one address space and one cgroup memory limit. This governor decides, per upsert and
against the pod's *live* memory headroom, how large an upsert we can commit: it picks the
per-call knobs (``max_parallel_partitions`` / ``max_parallel_files`` / ``max_buffered_bytes``)
that fit, and applies backpressure when the pod is full instead of letting it OOM.

Two layers, by design:

* This governor (Python) is the **planner**. It reads real headroom from cgroup, reserves the
  marginal cost of each in-flight upsert, and sizes knobs so the running total fits. It also
  accounts for *non-deltalite* writers for free: ``memory.current`` already includes whatever
  the MERGE fallbacks, full syncs and the interpreter are using right now, so measuring it is
  how every other Delta write on the pod is counted — we only ever *model* the marginal cost of
  the new upsert on top.
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
import time
import asyncio
import logging
import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

MB = 1024 * 1024

Mode = Literal["off", "advisory", "enforce"]

# --- Memory model coefficients (mirror deltalite_planner.py; see REPORT.md §5.5-5.7) --------

#: One-off, shared process floor: interpreter, imports, tokio runtime, object-store pools. Paid
#: once for the whole process, so it is a floor on the projected peak, not a per-upsert cost.
_PROCESS_BASELINE_MB = 500.0
#: Marginal cost of one in-flight upsert before any partition worker: snapshot/log state, plan,
#: channels, PK set bookkeeping.
_PER_UPSERT_FLOOR_MB = 300.0
#: The resident source batch is held for the whole upsert; roughly doubled while an interleaved
#: source is sliced per partition. Conservative (over-counting memory is the safe direction).
_SOURCE_RESIDENT_MULTIPLIER = 2.0
#: Cost of one concurrent partition worker on top of its write buffer (in-flight row groups, PK
#: set, transient source slice).
_PER_WORKER_OVERHEAD_MB = 150.0
#: Default output file target; the write buffer per worker is bounded by this.
_TARGET_FILE_SIZE_MB = 100.0
#: Beyond 4 partition workers the measured wall-clock gains vanish while memory keeps climbing.
_MAX_PARALLEL_PARTITIONS = 4


@dataclass(frozen=True)
class UpsertPlan:
    """A sizing decision for one upsert: the knobs, and the memory it is predicted to add."""

    max_parallel_partitions: int
    max_parallel_files: int
    max_buffered_bytes: int
    #: Predicted marginal peak RSS this upsert adds on top of the shared baseline, in MB.
    predicted_peak_mb: float
    #: False when even the most conservative single-worker config exceeds the available budget.
    fits: bool

    def as_upsert_kwargs(self) -> dict[str, int]:
        return {
            "max_parallel_partitions": self.max_parallel_partitions,
            "max_parallel_files": self.max_parallel_files,
            "max_buffered_bytes": self.max_buffered_bytes,
        }


def _predict_marginal_mb(source_mb: float, mpp: int, buffered_mb: float) -> float:
    """Marginal peak RSS one upsert adds: floor + resident source + workers + output buffer."""
    worker_mb = _TARGET_FILE_SIZE_MB + _PER_WORKER_OVERHEAD_MB
    return (
        _PER_UPSERT_FLOOR_MB
        + _SOURCE_RESIDENT_MULTIPLIER * source_mb
        + mpp * worker_mb
        + buffered_mb
    )


def size_upsert(available_mb: float, source_mb: float, n_partitions: int | None = None) -> UpsertPlan:
    """Pick the largest ``max_parallel_partitions`` whose marginal peak fits ``available_mb``.

    ``available_mb`` is the headroom this *single* upsert may add on top of what is already
    committed on the pod — not the whole pod. Strategy: start at the cap and step down; if even
    one worker with a shrunk buffer does not fit, return the minimal config with ``fits=False``
    so the caller can fall back to the MERGE (which is today's behaviour) rather than risk the pod.
    """
    partition_cap = _MAX_PARALLEL_PARTITIONS
    if n_partitions is not None and n_partitions >= 1:
        partition_cap = min(partition_cap, n_partitions)

    # Try the roomy config first, then a tight one (halved buffer / fewer readers) if nothing fits.
    for buffered_bytes, mpf in ((64 * MB, 4), (32 * MB, 2)):
        buffered_mb = buffered_bytes / MB
        for mpp in range(partition_cap, 0, -1):
            predicted = _predict_marginal_mb(source_mb, mpp, buffered_mb)
            if predicted <= available_mb:
                return UpsertPlan(mpp, mpf, buffered_bytes, round(predicted, 1), fits=True)

    # Nothing fits: report the smallest configuration (mpp=1, tight buffer) and its overshoot.
    minimal = _predict_marginal_mb(source_mb, 1, 32.0)
    return UpsertPlan(1, 2, 32 * MB, round(minimal, 1), fits=False)


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

    ``mode`` gates the rollout, matching the plan's stages:
      * ``off``      — do nothing; upserts use deltalite's own defaults (today's behaviour).
      * ``advisory`` — compute and log/emit the decision, but still use deltalite defaults for the
                       actual write. Zero behaviour change; validates the model on prod.
      * ``enforce``  — apply the chosen knobs and admission control (reserve + backpressure).
    """

    mode: Mode = "advisory"
    #: Fraction of the pod limit deltalite planning may target; the rest is slack for allocator
    #: retention, pyarrow buffers and anything unmodelled.
    safety: float = 0.8
    #: Headroom held back for the memory-*unpredictable* delta-rs MERGE (its RSS tracks table
    #: size, unlike deltalite) so a fallback burst can't collide with committed upsert reservations.
    merge_reserve_mb: float = 2048.0
    #: Longest an upsert will wait for the pod to free memory before falling back to the MERGE.
    #: 0 disables backpressure (reject-to-MERGE immediately when full).
    max_wait_s: float = 0.0
    #: Poll interval while waiting for headroom.
    poll_interval_s: float = 0.25
    #: Reject sources larger than this to deltalite (0 disables); mirrors the Rust
    #: ``DELTALITE_MAX_SOURCE_BYTES`` guard so we fall back *before* the crate raises.
    max_source_bytes: int = 2 * 1024 * 1024 * 1024
    #: Used only when the cgroup limit is unreadable (local dev). None + unreadable ⇒ conservative.
    limit_override_mb: float | None = None
    #: Shared process floor for the projected-peak estimate.
    baseline_mb: float = _PROCESS_BASELINE_MB

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
            merge_reserve_mb=_env_float("DELTALITE_GOVERNOR_MERGE_RESERVE_MB", 2048.0),
            max_wait_s=_env_float("DELTALITE_GOVERNOR_MAX_WAIT_S", 0.0),
            poll_interval_s=_env_float("DELTALITE_GOVERNOR_POLL_INTERVAL_S", 0.25),
            max_source_bytes=_env_int("DELTALITE_MAX_SOURCE_BYTES", 2 * 1024 * 1024 * 1024),
            limit_override_mb=float(override) if override else None,
        )


@dataclass
class Admission:
    """The outcome of an admission request, and the knobs to write with.

    ``proceed`` is True except when enforcing and the pod is genuinely full (or the source is too
    big) — in which case the caller falls back to the delta-rs MERGE, exactly as it does on any
    other deltalite refusal, so the sync is never affected.
    """

    proceed: bool
    upsert_kwargs: dict[str, int]
    mode: Mode
    predicted_peak_mb: float | None
    fits: bool
    waited_s: float = 0.0
    reject_reason: str | None = None
    #: Filled in on release with the observed cgroup delta, for predicted-vs-actual calibration.
    observed_delta_mb: float | None = field(default=None)


# --- The governor ----------------------------------------------------------------------------


class MemoryGovernor:
    """Process-wide admission control for deltalite upserts. Construct one per process."""

    def __init__(self, config: GovernorConfig | None = None, pod: PodMemory | None = None) -> None:
        self.config = config or GovernorConfig.from_env()
        self.pod = pod or PodMemory(limit_override_mb=self.config.limit_override_mb)
        self._lock = asyncio.Lock()
        self._reserved_mb = 0.0
        self._inflight = 0

    # -- accounting --------------------------------------------------------------------------

    def _available_mb_locked(self, limit_mb: float, current_mb: float | None) -> float:
        """Headroom a new upsert may consume, given what is already committed. Call under lock.

        ``committed = max(live usage, baseline + Σ reservations)`` guards both directions: if a
        reservation's memory hasn't materialised yet, the reservation term dominates; if something
        unmodelled grew (a MERGE), live usage dominates.
        """
        projected = self.config.baseline_mb + self._reserved_mb
        committed = max(current_mb, projected) if current_mb is not None else projected
        return limit_mb * self.config.safety - committed - self.config.merge_reserve_mb

    @contextlib.asynccontextmanager
    async def admit(self, *, source_bytes: int, n_partitions: int | None = None) -> AsyncIterator[Admission]:
        """Reserve headroom for one upsert and yield the knobs to run it with.

        Use as ``async with governor.admit(...) as adm``. The reservation is held for the whole
        ``with`` block (i.e. across the upsert) and released on exit, even on exception.
        """
        source_mb = source_bytes / MB

        if self.config.mode == "off":
            yield Admission(True, {}, "off", None, fits=True)
            return

        limit_mb = self.pod.limit_mb()
        # No cgroup limit visible (local dev, or unreadable): we cannot plan a budget safely, so
        # advise nothing and never block. Enforcement degrades to "use deltalite defaults".
        if limit_mb is None:
            unbudgeted = size_upsert(float("inf"), source_mb, n_partitions)
            yield Admission(True, {}, self.config.mode, unbudgeted.predicted_peak_mb, fits=True)
            return

        reject_reason: str | None = None
        proceed = True
        waited_s = 0.0
        reserved_here = 0.0
        admitted = False
        plan: UpsertPlan | None = None
        current_at_admit: float | None = None

        # Oversized source: fall back to the MERGE before the crate's own guard raises.
        if self.config.max_source_bytes and source_bytes > self.config.max_source_bytes:
            reject_reason = "source_too_big"
            proceed = self.config.mode != "enforce"
            plan = size_upsert(0.0, source_mb, n_partitions)
        else:
            start = time.monotonic()
            while True:
                async with self._lock:
                    current_mb = self.pod.current_mb()
                    available = self._available_mb_locked(limit_mb, current_mb)
                    plan = size_upsert(available, source_mb, n_partitions)
                    if plan.fits and self.config.mode == "enforce":
                        reserved_here = plan.predicted_peak_mb
                        self._reserved_mb += reserved_here
                        self._inflight += 1
                        admitted = True
                        current_at_admit = current_mb
                if plan.fits or self.config.mode != "enforce":
                    break
                remaining = self.config.max_wait_s - (time.monotonic() - start)
                if remaining <= 0:
                    proceed = False
                    reject_reason = "pod_full"
                    break
                await asyncio.sleep(min(self.config.poll_interval_s, remaining))
            waited_s = time.monotonic() - start

        upsert_kwargs = plan.as_upsert_kwargs() if admitted else {}
        adm = Admission(
            proceed=proceed,
            upsert_kwargs=upsert_kwargs,
            mode=self.config.mode,
            predicted_peak_mb=plan.predicted_peak_mb if plan else None,
            fits=plan.fits if plan else False,
            waited_s=round(waited_s, 3),
            reject_reason=reject_reason,
        )
        self._emit_decision(adm, source_mb)
        try:
            yield adm
        finally:
            if admitted:
                async with self._lock:
                    self._reserved_mb -= reserved_here
                    self._inflight -= 1
                # Best-effort predicted-vs-actual: how much did cgroup usage actually rise?
                if current_at_admit is not None:
                    now = self.pod.current_mb()
                    if now is not None:
                        adm.observed_delta_mb = round(now - current_at_admit, 1)

    # -- observability -----------------------------------------------------------------------

    def _emit_decision(self, adm: Admission, source_mb: float) -> None:
        """Log the decision and emit metrics. Never raises into the write path."""
        try:
            from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.metrics import (
                DELTALITE_GOVERNOR_ADMISSION_WAIT_SECONDS,
                DELTALITE_GOVERNOR_DECISION_TOTAL,
                DELTALITE_GOVERNOR_INFLIGHT,
                DELTALITE_GOVERNOR_PREDICTED_PEAK_MB,
                DELTALITE_GOVERNOR_RESERVED_MB,
            )

            outcome = adm.reject_reason or ("admitted" if adm.fits else "no_fit")
            DELTALITE_GOVERNOR_DECISION_TOTAL.labels(mode=adm.mode, outcome=outcome).inc()
            DELTALITE_GOVERNOR_INFLIGHT.set(self._inflight)
            DELTALITE_GOVERNOR_RESERVED_MB.set(self._reserved_mb)
            if adm.waited_s > 0:
                DELTALITE_GOVERNOR_ADMISSION_WAIT_SECONDS.observe(adm.waited_s)
            if adm.predicted_peak_mb is not None:
                DELTALITE_GOVERNOR_PREDICTED_PEAK_MB.observe(adm.predicted_peak_mb)
        except Exception:  # noqa: BLE001 - metrics are best-effort; never fail a write over them
            pass


_GOVERNOR: MemoryGovernor | None = None


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
