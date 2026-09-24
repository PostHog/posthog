import posthoganalytics
from posthoganalytics.metrics_capture import PostHogMetrics


def _metrics() -> PostHogMetrics | None:
    client = posthoganalytics.default_client
    return client.metrics if client is not None else None


def record_git_fetch(*, outcome: str, seconds: float, fetched_bytes: int) -> None:
    metrics = _metrics()
    if metrics is None:
        return
    attributes = {"outcome": outcome}
    metrics.count("error_tracking.repo_paths.git_fetches", 1, attributes=attributes)
    metrics.histogram("error_tracking.repo_paths.git_fetch.duration", seconds, unit="s", attributes=attributes)
    metrics.histogram("error_tracking.repo_paths.git_fetch.size", fetched_bytes, unit="By", attributes=attributes)
