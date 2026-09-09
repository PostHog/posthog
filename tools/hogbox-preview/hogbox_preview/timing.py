"""Lightweight stage timing for the preview bring-up.

The bring-up (and the deferred frontend swap) is a single multi-minute tool
invocation whose STDOUT is a strict ``url=``/``box_id=`` contract the workflow
parses — so progress can't go there. Without any output the CI log shows a
~6-minute void between the step start and ``url=``, which makes it impossible to
tell where the time actually goes. These helpers print
``[hogbox-preview +NNNs] <stage>`` breadcrumbs to STDERR at each major phase
boundary instead: per-stage visibility for free, no new dependency, and the
stdout contract stays untouched.

Elapsed is whole seconds since the tool started, measured with
``time.monotonic()`` so it's immune to wall-clock jumps and needs no formatting
library.

Two things beyond the breadcrumbs, both because reading a duration off the log
meant subtracting adjacent ``+NNNs`` lines by hand:

``span()`` times a block and records it. Breadcrumbs mark a *point*, so a stage
with no successor marker (or one that runs inside another) had no measurable
duration at all — ``docker pull`` and ``reset-db`` were ~2 minutes of the
bring-up and emitted nothing. Every ``run_long`` step is wrapped in one, so new
stages get timed without anyone remembering to add a marker.

``write_summary()`` puts the recorded spans in the job summary and emits one
machine-readable line. The breadcrumbs live only in a log that ages out in 90
days, which is why "is the preview getting slower?" has never been answerable
without scraping. The JSON line is deliberately the same shape a
``hogbox preview announced`` event would carry.
"""

from __future__ import annotations

import os
import sys
import json
import time
import pathlib
import contextlib
from collections.abc import Iterator

# Captured at import (process start) so every stage line is relative to the same
# t0 across both the backend (pen/restore) and the stack (checkout/migrate/...).
#
# The bring-up and the deferred frontend swap are two separate processes, so
# their breadcrumbs used to restart from +0s and couldn't be read as one
# timeline. HOGBOX_PREVIEW_T0 (unix seconds, exported once by the workflow)
# gives both an origin far enough back to cover the whole job; without it we
# fall back to process start and behave exactly as before.
_T0_ENV = os.environ.get("HOGBOX_PREVIEW_T0")
if _T0_ENV and _T0_ENV.strip().isdigit():
    _START = time.monotonic() - max(0.0, time.time() - int(_T0_ENV))
else:
    _START = time.monotonic()

# (name, seconds), in completion order. Spans nest, so a parent's duration
# includes its children — the summary shows both rather than trying to subtract.
_SPANS: list[tuple[str, float]] = []


def stage(message: str) -> None:
    """Emit one ``[hogbox-preview +NNNs] <message>`` line to STDERR."""
    elapsed = int(time.monotonic() - _START)
    sys.stderr.write(f"[hogbox-preview +{elapsed}s] {message}\n")
    sys.stderr.flush()


@contextlib.contextmanager
def span(name: str) -> Iterator[None]:
    """Time a block, record it, and breadcrumb both edges.

    The duration is recorded even when the block raises, so a failed run still
    reports which stage it died in and how long it burned first — today a
    restore timeout and a migrate failure look identical from outside the log.
    """
    started = time.monotonic()
    stage(f"{name} start")
    try:
        yield
    finally:
        elapsed = time.monotonic() - started
        _SPANS.append((name, elapsed))
        stage(f"{name} done in {elapsed:.1f}s")


def spans() -> list[tuple[str, float]]:
    """Recorded spans, in completion order."""
    return list(_SPANS)


def write_summary(*, title: str = "preview timings") -> None:
    """Append the recorded spans to the GH job summary and emit one JSON line.

    Safe to call on the failure path: partial spans are more useful than none.
    Never raises — timing must not be the thing that fails a preview.
    """
    if not _SPANS:
        return

    total = time.monotonic() - _START
    # Sum repeats instead of letting a dict keep only the last one: pull_image
    # retries run_long(name="pull") on a flaky ghcr handshake, so "pull" can be
    # recorded more than once. Keeping the last attempt would report the 5s
    # success while total_s still carried the two failed minutes. The table
    # below still lists every attempt on its own row; this line is the per-stage
    # total, which is the number you want when asking where the time went.
    stage_totals: dict[str, float] = {}
    for name, secs in _SPANS:
        stage_totals[name] = stage_totals.get(name, 0.0) + secs
    payload = {"total_s": round(total, 1), "stages": {name: round(secs, 1) for name, secs in stage_totals.items()}}
    sys.stderr.write(f"[hogbox-preview timings] {json.dumps(payload, sort_keys=True)}\n")
    sys.stderr.flush()

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    rows = "\n".join(f"| {name} | {secs:.1f} |" for name, secs in _SPANS)
    block = f"\n### {title}\n\n| stage | seconds |\n| --- | ---: |\n{rows}\n| **total** | **{total:.1f}** |\n"
    with contextlib.suppress(OSError):
        with pathlib.Path(summary_path).open("a", encoding="utf-8") as fh:
            fh.write(block)
