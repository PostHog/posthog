"""Node-run observability: one recorder for every terminal run transition (sql_v2_observability.md gap 1).

Every path that moves a NotebookNodeRun to a terminal status reports it here exactly once:
the sandbox callback, the direct lane, dispatch failures, and interrupts. The recorder
measures end-to-end duration against the run row's ``created_at``
(the only start clock that exists) and emits three sinks at once:

- a Prometheus histogram (Grafana / the rollout dashboard),
- its OTLP twin (the PostHog Metrics product),
- a ``notebook node run completed`` event (product analytics, sliceable per notebook).

Runs additionally carry phase timings in the envelope's ``timings`` dict. Kernel runs
report them from the sandbox (``sandbox/kernel/runner.py``): ``input_wait_s`` (waiting on
the data plane for referenced frames or the display fetch), ``download_s`` (the presigned
frame downloads), ``kernel_boot_s`` (ensuring the ipykernel is up — ~0 when already warm),
``exec_s`` (ipykernel cell execution), and ``sandbox_total_s`` (the whole
sandbox-side run). Direct (hogql) runs report them from the async query manager's status
(``sql_v2_direct._query_status_timings``): ``queued_s`` (enqueue -> Celery pickup) and
``clickhouse_s`` (pickup -> completion, i.e. HogQL compile + ClickHouse execution).
"""

import math
from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

import structlog
from prometheus_client import Histogram

from posthog.event_usage import report_user_or_team_action
from posthog.models import Team
from posthog.otel_metrics import OtelInstrumentFactory

from products.notebooks.backend.models import NotebookNodeRun

logger = structlog.get_logger(__name__)

NODE_RUN_COMPLETED_EVENT = "notebook node run completed"

# The terminal statuses, plus `timed_out` — a FAILED written by the direct lane's
# grace-expiry watchdog. Kept distinct so an expired query is a visible bucket rather
# than indistinguishable from a user error.
OUTCOME_DONE = "done"
OUTCOME_FAILED = "failed"
OUTCOME_INTERRUPTED = "interrupted"
OUTCOME_TIMED_OUT = "timed_out"

_OUTCOME_BY_STATUS = {
    NotebookNodeRun.Status.DONE: OUTCOME_DONE,
    NotebookNodeRun.Status.FAILED: OUTCOME_FAILED,
    NotebookNodeRun.Status.INTERRUPTED: OUTCOME_INTERRUPTED,
}

# Envelope timing keys -> phase label values. Anything else in `timings` is ignored, so a
# hostile or newer sandbox cannot mint unbounded label values.
_PHASE_BY_TIMING_KEY = {
    "input_wait_s": "input_wait",
    "download_s": "download",
    "kernel_boot_s": "kernel_boot",
    "exec_s": "exec",
    "sandbox_total_s": "sandbox_total",
    "queued_s": "queued",
    "clickhouse_s": "clickhouse",
}

# Headroom over the backend-measured run duration when bounding sandbox-reported timings:
# absorbs clock granularity and rounding without letting a forged value stretch far past
# the run's real wall clock.
_TIMING_CLOCK_SLACK_SECONDS = 60.0

_otel = OtelInstrumentFactory("notebooks")

NODE_RUN_SECONDS = Histogram(
    "posthog_notebooks_node_run_seconds",
    "End-to-end notebook node run duration: run-row creation to its terminal transition.",
    labelnames=["node_type", "outcome"],
    buckets=[0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600, 1200, 1800, 2700],
)
NODE_RUN_PHASE_SECONDS = Histogram(
    "posthog_notebooks_node_run_phase_seconds",
    "Phase durations of a node run, from the run envelope's timings.",
    labelnames=["phase", "node_type"],
    buckets=[0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600],
)


def outcome_for_status(status: str) -> str:
    return _OUTCOME_BY_STATUS.get(NotebookNodeRun.Status(status), OUTCOME_FAILED)


def record_node_run_terminal(run: NotebookNodeRun, outcome: str) -> None:
    """Report one terminal transition of `run`. Call only when this caller won the
    RUNNING -> terminal transition, so re-deliveries and racing pollers never double-count.

    Never raises — telemetry must not fail the run.
    """
    try:
        duration = max((timezone.now() - run.created_at).total_seconds(), 0.0)
        NODE_RUN_SECONDS.labels(node_type=run.node_type, outcome=outcome).observe(duration)
        _otel.record_histogram_twin(NODE_RUN_SECONDS, duration, {"node_type": run.node_type, "outcome": outcome})

        timings = _sanitized_timings(run.envelope, max_seconds=duration + _TIMING_CLOCK_SLACK_SECONDS)
        for phase, seconds in timings.items():
            NODE_RUN_PHASE_SECONDS.labels(phase=phase, node_type=run.node_type).observe(seconds)
            _otel.record_histogram_twin(NODE_RUN_PHASE_SECONDS, seconds, {"phase": phase, "node_type": run.node_type})

        _capture_completed_event(run, outcome, duration, timings)
    except Exception:
        logger.exception("notebook_node_run_metrics_failed", run_id=str(run.id), outcome=outcome)


def _sanitized_timings(envelope: Any, max_seconds: float) -> dict[str, float]:
    """Bound the envelope's self-reported timings before they touch shared histograms.

    The envelope is produced inside the sandbox, where user code can forge it — an absurd
    but JSON-legal value like 1e300 would permanently poison the process-wide histogram
    sums for every tenant. Every phase is a sub-span of the run, so the backend-measured
    run duration (plus clock slack) is a hard ceiling; anything above it is clamped.
    """
    raw = envelope.get("timings") if isinstance(envelope, dict) else None
    if not isinstance(raw, dict):
        return {}
    return {
        _PHASE_BY_TIMING_KEY[key]: min(float(value), max_seconds)
        for key, value in raw.items()
        if key in _PHASE_BY_TIMING_KEY and isinstance(value, int | float) and math.isfinite(value) and value >= 0
    }


def _capture_completed_event(
    run: NotebookNodeRun,
    outcome: str,
    duration: float,
    timings: dict[str, float],
) -> None:
    envelope = run.envelope if isinstance(run.envelope, dict) else {}
    properties: dict[str, Any] = {
        "notebook_short_id": run.notebook.short_id,
        "node_type": run.node_type,
        "outcome": outcome,
        "duration_seconds": round(duration, 3),
        "row_count": envelope.get("row_count"),
        "has_error": bool(run.error),
        **{f"{phase}_seconds": round(value, 3) for phase, value in timings.items()},
    }
    try:
        user = run.user
    except ObjectDoesNotExist:
        # The FK is db_constraint=False/DO_NOTHING: a hard-deleted user leaves a dangling
        # id, and descriptor access raises instead of reading back as None.
        user = None
    # Always resolve the run's own team: with team=None, report_user_or_team_action
    # attributes $groups to the user's *currently active* project, which can differ
    # from the project the run belongs to (multi-project users, personal API keys).
    team = Team.objects.filter(pk=run.team_id).first()
    report_user_or_team_action(NODE_RUN_COMPLETED_EVENT, properties, user=user, team=team)
