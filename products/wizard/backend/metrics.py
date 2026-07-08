from prometheus_client import Counter, Histogram

from products.wizard.backend.facade.contracts import WizardSessionDTO
from products.wizard.backend.facade.enums import RunPhase

_KNOWN_WORKFLOWS = {"posthog-integration"}

_TERMINAL_PHASES = {RunPhase.COMPLETED, RunPhase.ERROR}

_KNOWN_POLL_SOURCES = {"detector", "transport"}


def _workflow_label(workflow_id: str) -> str:
    return workflow_id if workflow_id in _KNOWN_WORKFLOWS else "other"


def poll_source_label(raw_source: str | None) -> str:
    return raw_source if raw_source in _KNOWN_POLL_SOURCES else "unknown"


WIZARD_SESSIONS_FINISHED_TOTAL = Counter(
    "posthog_wizard_sessions_finished_total",
    "Wizard sessions that transitioned into a terminal phase, observed at the upsert API",
    labelnames=["workflow", "outcome"],
)

WIZARD_SESSION_RUN_DURATION_SECONDS = Histogram(
    "posthog_wizard_session_run_duration_seconds",
    "Wall-clock wizard run duration (started_at to the terminal upsert), by outcome",
    labelnames=["workflow", "outcome"],
    buckets=(30, 60, 120, 300, 600, 1200, 1800, 3600, float("inf")),
)

WIZARD_LATEST_SESSION_REQUESTS_TOTAL = Counter(
    "posthog_wizard_latest_session_requests_total",
    "Poll requests against the latest-session endpoint, by caller source "
    "(detector/transport/unknown) and result (hit/empty/killswitch)",
    labelnames=["source", "result"],
)

WIZARD_PUBSUB_PUBLISH_TOTAL = Counter(
    "posthog_wizard_pubsub_publish_total",
    "Redis fan-out publishes of session updates, by outcome (published/failed)",
    labelnames=["outcome"],
)


def report_session_upserted(previous_run_phase: str | None, dto: WizardSessionDTO) -> None:
    if dto.run_phase not in _TERMINAL_PHASES or previous_run_phase in _TERMINAL_PHASES:
        return
    workflow = _workflow_label(dto.workflow_id)
    outcome = dto.run_phase.value
    WIZARD_SESSIONS_FINISHED_TOTAL.labels(workflow=workflow, outcome=outcome).inc()
    duration = (dto.updated_at - dto.started_at).total_seconds()
    if duration >= 0:
        WIZARD_SESSION_RUN_DURATION_SECONDS.labels(workflow=workflow, outcome=outcome).observe(duration)
