"""Replay Vision workflow + activity metrics.

Every metric is emitted twice from one `record_*` helper: a Prometheus instrument
(auto-scraped by the worker's combined metrics server, feeds Grafana) and an OTLP twin
with the same name and attributes pushed into the PostHog Metrics product via
posthog/otel_metrics.py (no-op unless OTEL_METRICS_EXPORT_URL/TOKEN are configured).
The twin derives its name and description from the prom instrument, and its recording
is swallowed so telemetry can never fail an activity.
"""

from prometheus_client import Counter, Gauge, Histogram
from temporalio import workflow

from posthog.otel_metrics import OtelInstrumentFactory

_otel = OtelInstrumentFactory("replay-vision")

REPLAY_VISION_OBSERVATIONS = Counter(
    "replay_vision_observations_total",
    "Observations by terminal status",
    ["status", "scanner_type"],
)

REPLAY_VISION_FAILURE_KINDS = Counter(
    "replay_vision_failure_kinds_total",
    "Failed observations broken down by FailureKind",
    ["kind", "scanner_type"],
)

REPLAY_VISION_INELIGIBLE_KINDS = Counter(
    "replay_vision_ineligible_kinds_total",
    "Ineligible observations broken down by IneligibleSessionKind",
    ["kind"],
)

# Extends past the default ceiling so multi-minute upload + provider-call activities don't all land in +Inf.
_ACTIVITY_DURATION_BUCKETS = (0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600)

REPLAY_VISION_ACTIVITY_DURATION = Histogram(
    "replay_vision_activity_duration_seconds",
    "Per-activity wall time",
    ["activity", "status"],
    buckets=_ACTIVITY_DURATION_BUCKETS,
)

_PROVIDER_CALL_BUCKETS = (0.5, 1, 2.5, 5, 10, 30, 60, 120, 300)

REPLAY_VISION_PROVIDER_CALL = Histogram(
    "replay_vision_provider_call_seconds",
    "Provider call latency",
    ["provider", "model", "scanner_type", "outcome"],
    buckets=_PROVIDER_CALL_BUCKETS,
)

REPLAY_VISION_MISSION_PASSES = Counter(
    "replay_vision_mission_passes_total",
    "Full mission passes sent to the provider; rate against observations shows how hard the retry layers multiply",
    ["model", "path"],
)

REPLAY_VISION_QUOTA_EXHAUSTED_SKIPS = Counter(
    "replay_vision_quota_exhausted_skips_total",
    "Observations skipped because the org's monthly credit quota was exhausted",
    ["scanner_type"],
)

REPLAY_VISION_CREDITS_CONSUMED = Counter(
    "replay_vision_credits_consumed_total",
    "Credits billed onto usage receipts at observation success",
    ["scanner_type", "model"],
)

REPLAY_VISION_BACKFILL_TICK_OUTCOMES = Counter(
    "replay_vision_backfill_tick_outcomes_total",
    "Backfill tick outcomes: dispatched, throttled, paused on quota, skipped, or completed",
    ["outcome"],
)

REPLAY_VISION_SWEEP_OUTCOMES = Counter(
    "replay_vision_sweep_outcomes_total",
    "Sweep tick outcomes: throttled at an in-flight cap, capped by the scanner's own credit limit "
    "(settled spend, which skips the window for good, or in-flight reservations, which preserve the "
    "watermark), no candidates, or candidates found",
    ["outcome"],
)

# The admission lock gives up after a 2s lock_timeout, so waits are capped, not worth a histogram;
# here instead, as attempts that found the row held and deferred to the activity's retry policy.
REPLAY_VISION_SCANNER_ADMISSION_BUSY = Counter(
    "replay_vision_scanner_admission_busy_total",
    "Capped-scanner admissions that found the row lock held and were deferred to the activity retry",
    ["scanner_type"],
)

REPLAY_VISION_SCANNER_LIMIT_REACHED = Counter(
    "replay_vision_scanner_limit_reached_total",
    "Requests refused because a per-scanner credit limit left no room, by the API surface that refused",
    ["surface"],
)

REPLAY_VISION_DEEP_SWEEP_FAILURES = Counter(
    "replay_vision_deep_sweep_failures_total",
    "Deep catch-up passes that failed inside an otherwise successful sweep tick; separate from sweep "
    "outcomes so a tick still counts exactly once there",
)

REPLAY_VISION_DEEP_CANDIDATES = Counter(
    "replay_vision_deep_candidates_total",
    "Sessions the catch-up pass found that the frequent sweep had missed. This is the pass's whole "
    "justification, so it is the number to weigh against what its wide-lookback query costs",
)

REPLAY_VISION_SWEEP_CANDIDATE_PAGE_FULL = Counter(
    "replay_vision_sweep_candidate_page_full_total",
    "Sweep ticks whose candidate page filled, meaning the window held more sessions than one tick "
    "could correlate; a scanner stuck at this is no longer keeping up with its own window",
)

REPLAY_VISION_SWEEP_CANDIDATES = Counter(
    "replay_vision_sweep_candidates_total",
    "Candidate sessions returned to sweeps for dispatch",
)

# Creation to success spans queueing, rasterization, upload, and the provider call.
_E2E_BUCKETS = (30.0, 60.0, 120.0, 300.0, 600.0, 1200.0, 1800.0, 3600.0, 7200.0)

REPLAY_VISION_OBSERVATION_E2E = Histogram(
    "replay_vision_observation_e2e_seconds",
    "Wall time from observation creation to success",
    ["scanner_type"],
    buckets=_E2E_BUCKETS,
)

REPLAY_VISION_SIDE_EFFECT_FAILURES = Counter(
    "replay_vision_side_effect_failures_total",
    "Failed attempts of fail-soft post-success side effects",
    ["effect"],
)

REPLAY_VISION_CONSENT_SKIPS = Counter(
    "replay_vision_consent_skips_total",
    "Scans skipped because the organization has not approved AI data processing",
    ["scanner_type"],
)

REPLAY_VISION_ENQUEUE_CLAIM_FAILURES = Counter(
    "replay_vision_enqueue_claim_failures_total",
    "Redis enqueue-claim operations that failed (claims fail open, so failures over-admit)",
    ["operation"],
)

REPLAY_VISION_ACTION_OCCURRENCES_DROPPED = Counter(
    "replay_vision_action_occurrences_dropped_total",
    "Vision-action occurrences claimed but permanently dropped because the child workflow start failed",
)

REPLAY_VISION_ACTION_RUNS_REAPED = Counter(
    "replay_vision_action_runs_reaped_total",
    "VisionActionRun rows stuck in running whose workflow was gone, failed by the reaper",
)

REPLAY_VISION_GEMINI_CLEANUP_BACKLOG = Gauge(
    "replay_vision_gemini_cleanup_backlog",
    "Tracked Gemini files awaiting cleanup (a growing backlog means the sweep is losing)",
)


def record_observation(status: str, scanner_type: str) -> None:
    labels = {"status": status, "scanner_type": scanner_type}
    REPLAY_VISION_OBSERVATIONS.labels(**labels).inc()
    _otel.record_counter_twin(REPLAY_VISION_OBSERVATIONS, 1, labels)


def record_failure_kind(kind: str, scanner_type: str) -> None:
    labels = {"kind": kind, "scanner_type": scanner_type}
    REPLAY_VISION_FAILURE_KINDS.labels(**labels).inc()
    _otel.record_counter_twin(REPLAY_VISION_FAILURE_KINDS, 1, labels)


def record_ineligible_kind(kind: str) -> None:
    REPLAY_VISION_INELIGIBLE_KINDS.labels(kind=kind).inc()
    _otel.record_counter_twin(REPLAY_VISION_INELIGIBLE_KINDS, 1, {"kind": kind})


def record_activity_duration(activity: str, status: str, seconds: float) -> None:
    labels = {"activity": activity, "status": status}
    REPLAY_VISION_ACTIVITY_DURATION.labels(**labels).observe(seconds)
    _otel.record_histogram_twin(REPLAY_VISION_ACTIVITY_DURATION, seconds, labels)


def record_provider_call(provider: str, model: str, scanner_type: str, outcome: str, seconds: float) -> None:
    labels = {"provider": provider, "model": model, "scanner_type": scanner_type, "outcome": outcome}
    REPLAY_VISION_PROVIDER_CALL.labels(**labels).observe(seconds)
    _otel.record_histogram_twin(REPLAY_VISION_PROVIDER_CALL, seconds, labels)


def record_mission_pass(model: str, path: str) -> None:
    labels = {"model": model, "path": path}
    REPLAY_VISION_MISSION_PASSES.labels(**labels).inc()
    _otel.record_counter_twin(REPLAY_VISION_MISSION_PASSES, 1, labels)


def record_quota_exhausted_skip(scanner_type: str) -> None:
    REPLAY_VISION_QUOTA_EXHAUSTED_SKIPS.labels(scanner_type=scanner_type).inc()
    _otel.record_counter_twin(REPLAY_VISION_QUOTA_EXHAUSTED_SKIPS, 1, {"scanner_type": scanner_type})


def record_scanner_admission_busy(scanner_type: str) -> None:
    REPLAY_VISION_SCANNER_ADMISSION_BUSY.labels(scanner_type=scanner_type).inc()
    _otel.record_counter_twin(REPLAY_VISION_SCANNER_ADMISSION_BUSY, 1, {"scanner_type": scanner_type})


def record_scanner_limit_reached(surface: str) -> None:
    """`surface` is "on_demand", "bulk", "evaluation", "max_tool", or "admission": the path that refused the work."""
    REPLAY_VISION_SCANNER_LIMIT_REACHED.labels(surface=surface).inc()
    _otel.record_counter_twin(REPLAY_VISION_SCANNER_LIMIT_REACHED, 1, {"surface": surface})


def record_credits_consumed(scanner_type: str, model: str, credits: int) -> None:
    labels = {"scanner_type": scanner_type, "model": model}
    REPLAY_VISION_CREDITS_CONSUMED.labels(**labels).inc(credits)
    _otel.record_counter_twin(REPLAY_VISION_CREDITS_CONSUMED, credits, labels)


def record_sweep_outcome(outcome: str, candidates: int = 0) -> None:
    REPLAY_VISION_SWEEP_OUTCOMES.labels(outcome=outcome).inc()
    _otel.record_counter_twin(REPLAY_VISION_SWEEP_OUTCOMES, 1, {"outcome": outcome})
    if candidates > 0:
        REPLAY_VISION_SWEEP_CANDIDATES.inc(candidates)
        _otel.record_counter_twin(REPLAY_VISION_SWEEP_CANDIDATES, candidates, {})


def record_deep_candidates(count: int) -> None:
    REPLAY_VISION_DEEP_CANDIDATES.inc(count)
    _otel.record_counter_twin(REPLAY_VISION_DEEP_CANDIDATES, count, {})


def record_candidate_page_full() -> None:
    REPLAY_VISION_SWEEP_CANDIDATE_PAGE_FULL.inc()
    _otel.record_counter_twin(REPLAY_VISION_SWEEP_CANDIDATE_PAGE_FULL, 1, {})


def record_deep_sweep_failure() -> None:
    REPLAY_VISION_DEEP_SWEEP_FAILURES.inc()
    _otel.record_counter_twin(REPLAY_VISION_DEEP_SWEEP_FAILURES, 1, {})


def record_backfill_tick_outcome(outcome: str) -> None:
    REPLAY_VISION_BACKFILL_TICK_OUTCOMES.labels(outcome=outcome).inc()
    _otel.record_counter_twin(REPLAY_VISION_BACKFILL_TICK_OUTCOMES, 1, {"outcome": outcome})


def record_observation_e2e(scanner_type: str, seconds: float) -> None:
    labels = {"scanner_type": scanner_type}
    REPLAY_VISION_OBSERVATION_E2E.labels(**labels).observe(seconds)
    _otel.record_histogram_twin(REPLAY_VISION_OBSERVATION_E2E, seconds, labels)


def record_side_effect_failure(effect: str) -> None:
    REPLAY_VISION_SIDE_EFFECT_FAILURES.labels(effect=effect).inc()
    _otel.record_counter_twin(REPLAY_VISION_SIDE_EFFECT_FAILURES, 1, {"effect": effect})


def record_consent_skip(scanner_type: str) -> None:
    REPLAY_VISION_CONSENT_SKIPS.labels(scanner_type=scanner_type).inc()
    _otel.record_counter_twin(REPLAY_VISION_CONSENT_SKIPS, 1, {"scanner_type": scanner_type})


def record_enqueue_claim_failure(operation: str) -> None:
    REPLAY_VISION_ENQUEUE_CLAIM_FAILURES.labels(operation=operation).inc()
    _otel.record_counter_twin(REPLAY_VISION_ENQUEUE_CLAIM_FAILURES, 1, {"operation": operation})


def record_vision_action_occurrence_dropped() -> None:
    # Callable from workflow code: replays must not double-count.
    if workflow.in_workflow() and workflow.unsafe.is_replaying():
        return
    REPLAY_VISION_ACTION_OCCURRENCES_DROPPED.inc()
    _otel.record_counter_twin(REPLAY_VISION_ACTION_OCCURRENCES_DROPPED, 1, {})


def record_vision_action_runs_reaped(count: int) -> None:
    REPLAY_VISION_ACTION_RUNS_REAPED.inc(count)
    _otel.record_counter_twin(REPLAY_VISION_ACTION_RUNS_REAPED, count, {})


def record_gemini_cleanup_backlog(count: int) -> None:
    REPLAY_VISION_GEMINI_CLEANUP_BACKLOG.set(count)
    _otel.record_gauge_twin(REPLAY_VISION_GEMINI_CLEANUP_BACKLOG, count)
