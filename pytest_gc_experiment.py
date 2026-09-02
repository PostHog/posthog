"""Experiment-only pytest plugin that applies one GC configuration and reports its cost.

Loaded explicitly with `-p pytest_gc_experiment` by ci-backend-gc-experiment.yml; nothing
in pytest.ini references it. GC_EXPERIMENT names the configuration to apply once the root
conftest has closed the boot GC window. Unknown names keep the repo's current setup, so
allocator and environment variants can carry a label without changing the collector.

At session end the plugin writes GC_EXPERIMENT_RESULT (default gc-experiment-result.json)
with wall and CPU time of the test phase, time spent inside the collector per generation,
and peak RSS.
"""

import gc
import os
import sys
import json
import time
import resource
from typing import Any

import pytest

VARIANT = os.environ.get("GC_EXPERIMENT", "baseline")
RESULT_PATH = os.environ.get("GC_EXPERIMENT_RESULT", "gc-experiment-result.json")

_gc_seconds = [0.0, 0.0, 0.0]
_gc_runs = [0, 0, 0]
_gc_collected = [0, 0, 0]
_gc_started: dict[int, float] = {}
_phase: dict[str, Any] = {}


def _track_gc(phase: str, info: dict[str, int]) -> None:
    generation = info["generation"]
    if phase == "start":
        _gc_started[generation] = time.perf_counter()
        return
    started = _gc_started.pop(generation, None)
    if started is not None:
        _gc_seconds[generation] += time.perf_counter() - started
    _gc_runs[generation] += 1
    _gc_collected[generation] += info["collected"]


gc.callbacks.append(_track_gc)

# stock_gc reproduces the interpreter defaults from before the boot window existed:
# pytest_boot_gc has already disabled the collector by the time this module imports,
# and django.setup() runs next.
if VARIANT == "stock_gc":
    gc.enable()


def pytest_sessionstart(session: pytest.Session) -> None:
    # The root conftest disables GC again at import time; collection must run with it on.
    if VARIANT == "stock_gc":
        gc.enable()


@pytest.hookimpl(wrapper=True)
def pytest_collection_finish(session: pytest.Session):
    # With GC already enabled the root conftest's window close returns early:
    # no freeze, thresholds stay at (700, 10, 10).
    if VARIANT == "stock_gc":
        gc.enable()
    result = yield
    if VARIANT == "freeze_stock_thresholds":
        gc.set_threshold(2000, 10, 10)  # CPython 3.13 defaults
    elif VARIANT == "high_thresholds":
        gc.set_threshold(200_000, 50, 50)
    elif VARIANT == "no_gc":
        gc.disable()
    return result


@pytest.hookimpl(wrapper=True)
def pytest_runtestloop(session: pytest.Session):
    _phase["gc_enabled"] = gc.isenabled()
    _phase["gc_threshold"] = gc.get_threshold()
    _phase["gc_frozen"] = gc.get_freeze_count()
    _phase["wall_start"] = time.perf_counter()
    _phase["cpu_start"] = time.process_time()
    result = yield
    _phase["wall_s"] = time.perf_counter() - _phase["wall_start"]
    _phase["cpu_s"] = time.process_time() - _phase["cpu_start"]
    return result


def _max_rss_mb() -> float:
    max_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return round(max_rss / divisor, 1)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    final_collect_s = 0.0
    if VARIANT == "no_gc":
        started = time.perf_counter()
        gc.collect()
        final_collect_s = time.perf_counter() - started
    result = {
        "variant": VARIANT,
        "python": sys.version.split()[0],
        "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
        "malloc_arena_max": os.environ.get("MALLOC_ARENA_MAX"),
        "ld_preload": os.environ.get("LD_PRELOAD"),
        "gc_enabled": _phase.get("gc_enabled"),
        "gc_threshold": _phase.get("gc_threshold"),
        "gc_frozen": _phase.get("gc_frozen"),
        "tests": session.testscollected,
        "failed": session.testsfailed,
        "exitstatus": int(exitstatus),
        "test_phase_wall_s": round(_phase.get("wall_s", 0.0), 2),
        "test_phase_cpu_s": round(_phase.get("cpu_s", 0.0), 2),
        "gc_seconds": [round(s, 3) for s in _gc_seconds],
        "gc_seconds_total": round(sum(_gc_seconds), 3),
        "gc_runs": list(_gc_runs),
        "gc_collected": list(_gc_collected),
        "final_collect_s": round(final_collect_s, 3),
        "max_rss_mb": _max_rss_mb(),
    }
    with open(RESULT_PATH, "w") as handle:
        json.dump(result, handle, indent=2)
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(f"GC_EXPERIMENT_RESULT {json.dumps(result)}")
