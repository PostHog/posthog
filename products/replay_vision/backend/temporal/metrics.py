"""Prometheus metrics for the Replay Vision workflow + activities; auto-scraped by the worker's combined metrics server."""

from prometheus_client import Counter, Histogram

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

REPLAY_VISION_PROVIDER_CALL = Histogram(
    "replay_vision_provider_call_seconds",
    "Provider call latency",
    ["provider", "model", "scanner_type", "outcome"],
    buckets=(0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)
