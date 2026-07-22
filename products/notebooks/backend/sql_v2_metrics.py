"""Node-run observability: one recorder for every terminal run transition (sql_v2_observability.md gap 1).

Every path that moves a NotebookNodeRun to a terminal status reports it here exactly once:
the sandbox callback, the direct lane, dispatch failures, interrupts, and the stale-run
reaper. The recorder measures end-to-end duration against the run row's ``created_at``
(the only start clock that exists) and emits three sinks at once:

- a Prometheus histogram (Grafana / the rollout dashboard),
- its OTLP twin (the PostHog Metrics product),
- a ``notebook node run completed`` event (product analytics, sliceable per notebook).

Kernel runs additionally carry sandbox-side phase timings in the envelope's ``timings``
dict (see ``sandbox/kernel/runner.py``): ``input_wait_s`` (waiting on the data plane for
referenced frames or the display fetch), ``download_s`` (the presigned frame downloads),
``exec_s`` (ipykernel cell execution), and ``sandbox_total_s`` (the whole sandbox-side run).
"""

from typing import Any, Optional, Protocol

from django.utils import timezone

import structlog
from prometheus_client import Histogram

from posthog.event_usage import report_user_or_team_action
from posthog.models import Team
from posthog.otel_metrics import OtelInstrumentFactory

from products.notebooks.backend.models import NotebookNodeRun

logger = structlog.get_logger(__name__)

NODE_RUN_COMPLETED_EVENT = "notebook node run completed"

# The terminal statuses, plus `timed_out` — a FAILED written by a watchdog (the direct
# lane's grace expiry or the stale-run reaper). Kept distinct so a hung sandbox is a
# visible bucket rather than indistinguishable from a user error.
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
    "exec_s": "exec",
    "sandbox_total_s": "sandbox_total",
}

_otel = OtelInstrumentFactory("notebooks")

NODE_RUN_SECONDS = Histogram(
    "posthog_notebooks_node_run_seconds",
    "End-to-end notebook node run duration: run-row creation to its terminal transition.",
    labelnames=["node_type", "outcome"],
    buckets=[0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600, 1200, 1800, 2700],
)
KERNEL_PHASE_SECONDS = Histogram(
    "posthog_notebooks_kernel_phase_seconds",
    "Sandbox-reported phase durations of a node run, from the callback envelope's timings.",
    labelnames=["phase", "node_type"],
    buckets=[0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600],
)


class _CaptureFn(Protocol):
    def __call__(self, *, distinct_id: str, event: str, properties: dict[str, Any]) -> None: ...


def outcome_for_status(status: str) -> str:
    return _OUTCOME_BY_STATUS.get(NotebookNodeRun.Status(status), OUTCOME_FAILED)


def record_node_run_terminal(run: NotebookNodeRun, outcome: str, capture: Optional[_CaptureFn] = None) -> None:
    """Report one terminal transition of `run`. Call only when this caller won the
    RUNNING -> terminal transition, so re-deliveries and racing pollers never double-count.

    `capture` overrides the analytics sink for non-request contexts whose global client may
    never flush (the Celery reaper passes `ph_scoped_capture`'s function); the default goes
    through `report_user_or_team_action`. Never raises — telemetry must not fail the run.
    """
    try:
        duration = max((timezone.now() - run.created_at).total_seconds(), 0.0)
        NODE_RUN_SECONDS.labels(node_type=run.node_type, outcome=outcome).observe(duration)
        _otel.record_histogram_twin(NODE_RUN_SECONDS, duration, {"node_type": run.node_type, "outcome": outcome})

        timings = _sanitized_timings(run.envelope)
        for key, seconds in timings.items():
            phase = _PHASE_BY_TIMING_KEY[key]
            KERNEL_PHASE_SECONDS.labels(phase=phase, node_type=run.node_type).observe(seconds)
            _otel.record_histogram_twin(KERNEL_PHASE_SECONDS, seconds, {"phase": phase, "node_type": run.node_type})

        _capture_completed_event(run, outcome, duration, timings, capture)
    except Exception:
        logger.exception("notebook_node_run_metrics_failed", run_id=str(run.id), outcome=outcome)


def _sanitized_timings(envelope: Any) -> dict[str, float]:
    raw = envelope.get("timings") if isinstance(envelope, dict) else None
    if not isinstance(raw, dict):
        return {}
    return {
        key: float(value)
        for key, value in raw.items()
        if key in _PHASE_BY_TIMING_KEY and isinstance(value, int | float) and value >= 0
    }


def _capture_completed_event(
    run: NotebookNodeRun,
    outcome: str,
    duration: float,
    timings: dict[str, float],
    capture: Optional[_CaptureFn],
) -> None:
    envelope = run.envelope if isinstance(run.envelope, dict) else {}
    properties: dict[str, Any] = {
        "notebook_short_id": run.notebook.short_id,
        "node_type": run.node_type,
        "outcome": outcome,
        "duration_seconds": round(duration, 3),
        "row_count": envelope.get("row_count"),
        "has_error": bool(run.error),
        **{f"{_PHASE_BY_TIMING_KEY[key]}_seconds": round(value, 3) for key, value in timings.items()},
    }
    if capture is not None:
        distinct_id = run.user.distinct_id if run.user and run.user.distinct_id else None
        if distinct_id is None:
            team = Team.objects.filter(pk=run.team_id).only("uuid").first()
            distinct_id = str(team.uuid) if team else None
        if distinct_id:
            capture(distinct_id=distinct_id, event=NODE_RUN_COMPLETED_EVENT, properties=properties)
        return
    team = None if run.user else Team.objects.filter(pk=run.team_id).first()
    report_user_or_team_action(NODE_RUN_COMPLETED_EVENT, properties, user=run.user, team=team)
