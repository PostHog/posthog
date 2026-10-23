"""SDK metrics of the anomaly scoring tick. Attributes stay low cardinality, so ids go to the logs only."""

import posthoganalytics
from posthoganalytics.metrics_capture import PostHogMetrics
from temporalio import workflow


def _metrics() -> PostHogMetrics | None:
    # A replayed workflow runs its code again, and the values were already recorded the first time.
    if workflow.in_workflow() and workflow.unsafe.is_replaying():
        return None
    client = posthoganalytics.default_client
    return client.metrics if client is not None else None


def record_pick(*, status: str, interval: str, duration_ms: float, events: int) -> None:
    metrics = _metrics()
    if metrics is None:
        return
    attributes = {"status": status, "interval": interval}
    metrics.count("anomaly_scoring.picks", 1, attributes=attributes)
    metrics.histogram("anomaly_scoring.query.duration", duration_ms, unit="ms", attributes=attributes)
    if events:
        metrics.count("anomaly_scoring.events", events, attributes={"interval": interval})


def record_candidates(candidates: int) -> None:
    metrics = _metrics()
    if metrics is not None:
        metrics.gauge("anomaly_scoring.candidates", candidates, attributes={})
