"""Rough knob tuning for deltalite: "we run N concurrent upserts on a pod with M MB
of memory -- what should mpp / mpf be?"

This is deliberately a heuristic, not a capacity model. The measurements behind it
established the *shape* of deltalite's memory behaviour, and the shape is all this
module relies on:

* Peak memory never tracks target-table size. It tracks the resident source batch,
  the number of concurrent partition workers (`max_parallel_partitions`, "mpp"), and
  the write-buffer / byte-budget knobs.
* `max_parallel_partitions` is the memory dial. Each concurrent partition worker
  costs roughly its write buffer (`target_file_size`, 100 MB by default) plus
  in-flight row groups.
* `max_parallel_files` ("mpf") is a wall-clock dial with little memory effect of its
  own -- decoded data in flight is capped by the byte budget, not by mpf.
* Upserts running as threads in one process share the interpreter/runtime overhead
  and do not peak simultaneously, so a process fits noticeably more than
  N x (single-upsert peak).

Absolute numbers vary with row width, Parquet row-group sizing and hardware, so treat
the output as a starting point and validate under real load. The process-global
ceilings in `deltalite_core::limits` (DELTALITE_PROCESS_* env vars) are the hard
backstop either way.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MB = 1024 * 1024

#: Keep this fraction of pod memory for everything that is not deltalite (interpreter,
#: pyarrow buffers in flight, allocator slack).
_SAFETY = 0.8

#: One-off process overhead (interpreter, imports, tokio runtime, object-store pools).
_PROCESS_OVERHEAD_MB = 500

#: Rough marginal cost of one in-flight upsert before any partition worker spins up
#: (snapshot/log state, plan, channels). Staggered peaks are already baked in.
_PER_UPSERT_FLOOR_MB = 300

#: Rough cost of one concurrent partition worker on top of its write buffer
#: (in-flight row groups, PK set, transient source slice).
_PER_WORKER_OVERHEAD_MB = 150


@dataclass(frozen=True)
class Knobs:
    """A suggested starting configuration, plus how it was arrived at."""

    max_parallel_partitions: int
    max_parallel_files: int
    max_buffered_bytes: int
    #: Memory this plan roughly assumes one in-flight upsert may use.
    per_upsert_budget_mb: float
    #: False when even the most conservative knobs look too big for the pod.
    fits: bool
    #: Suggested process-global ceilings (the env vars `deltalite_core` reads).
    env: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_upsert_kwargs(self) -> dict:
        """Keyword arguments for `DeltaLiteTable.upsert`."""
        return {
            "max_parallel_partitions": self.max_parallel_partitions,
            "max_parallel_files": self.max_parallel_files,
            "max_buffered_bytes": self.max_buffered_bytes,
        }


def plan(
    concurrent_upserts: int,
    pod_memory_mb: float,
    *,
    source_mb: float | None = None,
    target_file_size_mb: float = 100.0,
) -> Knobs:
    """Suggest mpp / mpf / byte-budget knobs for `concurrent_upserts` upsert threads
    in one process on a pod with `pod_memory_mb` of memory.

    `source_mb` is the typical resident size of one upsert's source batch; when not
    given, a note reminds you that the source is the term nothing else bounds.
    """
    if concurrent_upserts < 1:
        raise ValueError("concurrent_upserts must be >= 1")
    if pod_memory_mb <= 0:
        raise ValueError("pod_memory_mb must be positive")
    if target_file_size_mb <= 0:
        raise ValueError("target_file_size_mb must be positive")

    notes: list[str] = []

    usable_mb = pod_memory_mb * _SAFETY - _PROCESS_OVERHEAD_MB
    per_upsert_mb = usable_mb / concurrent_upserts

    # The floor one upsert needs before any partition worker: bookkeeping plus the
    # resident source (held for the whole upsert; roughly doubled while interleaved
    # sources are sliced per partition).
    floor_mb = _PER_UPSERT_FLOOR_MB + (2.0 * source_mb if source_mb is not None else 0.0)
    if source_mb is None:
        notes.append(
            "source size not given: the resident source batch is the one memory term "
            "no knob bounds, so re-check against your largest batches"
        )

    worker_mb = target_file_size_mb + _PER_WORKER_OVERHEAD_MB
    headroom_mb = per_upsert_mb - floor_mb

    # mpp: however many partition workers fit in the headroom, kept between 1 and 4
    # (beyond 4 the measured wall-clock gains vanish while memory keeps climbing).
    mpp = max(1, min(4, int(headroom_mb // worker_mb)))
    tight = headroom_mb < worker_mb

    # mpf is a wall-clock knob; 4 is the measured sweet spot, halved when tight so
    # fewer decoded batches sit waiting for budget.
    mpf = 2 if tight else 4
    buffered = 32 * MB if tight else 64 * MB

    fits = headroom_mb >= worker_mb * 0.75  # allow a modest squeeze at mpp=1
    if not fits:
        notes.append(
            f"~{per_upsert_mb:.0f} MB per upsert is below the ~{floor_mb + worker_mb:.0f} MB "
            "a single-worker upsert wants: reduce concurrent upserts, shrink source "
            "batches, or use a bigger pod"
        )
    if tight and fits:
        notes.append("memory is tight: knobs reduced to their most conservative settings")

    # Process-global ceilings: cap total in-flight work at roughly four upserts' worth
    # of per-call knobs -- threads do not peak together, so this holds the process
    # bound without serialising everything.
    burst = min(concurrent_upserts, 4)
    env = {
        "DELTALITE_PROCESS_MAX_PARALLEL_PARTITIONS": str(mpp * burst),
        "DELTALITE_PROCESS_MAX_PARALLEL_FILES": str(mpf * burst),
        "DELTALITE_PROCESS_MAX_BUFFERED_BYTES": str(buffered * burst),
    }

    return Knobs(
        max_parallel_partitions=mpp,
        max_parallel_files=mpf,
        max_buffered_bytes=buffered,
        per_upsert_budget_mb=round(per_upsert_mb, 1),
        fits=fits,
        env=env,
        notes=notes,
    )


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Suggest deltalite knobs for a pod")
    ap.add_argument("concurrent_upserts", type=int)
    ap.add_argument("pod_memory_mb", type=float)
    ap.add_argument("--source-mb", type=float, default=None)
    ap.add_argument("--target-file-size-mb", type=float, default=100.0)
    args = ap.parse_args()
    k = plan(
        args.concurrent_upserts,
        args.pod_memory_mb,
        source_mb=args.source_mb,
        target_file_size_mb=args.target_file_size_mb,
    )
    print(f"fits={k.fits}  per-upsert budget ~{k.per_upsert_budget_mb} MB")
    print(f"upsert kwargs: {k.as_upsert_kwargs()}")
    for kk, v in k.env.items():
        print(f"env: {kk}={v}")
    for n in k.notes:
        print(f"note: {n}")
