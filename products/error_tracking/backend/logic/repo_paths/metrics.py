from prometheus_client import Counter, Histogram

_MB = 1024 * 1024

GIT_FETCHES = Counter(
    "error_tracking_repo_paths_git_fetches_total",
    "Git fetches of the file list of one commit, by outcome",
    labelnames=("outcome",),
)
GIT_FETCH_DURATION = Histogram(
    "error_tracking_repo_paths_git_fetch_duration_seconds",
    "Duration of one git fetch and listing, by outcome",
    labelnames=("outcome",),
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300),
)
GIT_FETCH_SIZE = Histogram(
    "error_tracking_repo_paths_git_fetch_bytes",
    "Bytes that one git fetch wrote to disk, by outcome",
    labelnames=("outcome",),
    buckets=tuple(n * _MB for n in (1, 4, 16, 64, 128, 256, 512)),
)


def record_git_fetch(*, outcome: str, seconds: float, fetched_bytes: int) -> None:
    GIT_FETCHES.labels(outcome=outcome).inc()
    GIT_FETCH_DURATION.labels(outcome=outcome).observe(seconds)
    GIT_FETCH_SIZE.labels(outcome=outcome).observe(fetched_bytes)
