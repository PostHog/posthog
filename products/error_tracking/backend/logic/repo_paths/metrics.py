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

JOBS = Counter(
    "error_tracking_repo_paths_jobs_total",
    "Release file list jobs, by outcome",
    labelnames=("outcome",),
)
FILE_LIST_PATHS = Histogram(
    "error_tracking_repo_paths_file_list_paths",
    "Paths in one stored file list",
    buckets=(100, 1_000, 10_000, 50_000, 100_000, 200_000),
)


def record_git_fetch(*, outcome: str, seconds: float, fetched_bytes: int) -> None:
    GIT_FETCHES.labels(outcome=outcome).inc()
    GIT_FETCH_DURATION.labels(outcome=outcome).observe(seconds)
    GIT_FETCH_SIZE.labels(outcome=outcome).observe(fetched_bytes)


def record_job_outcome(outcome: str) -> None:
    JOBS.labels(outcome=outcome).inc()


def record_file_list_size(paths: int) -> None:
    FILE_LIST_PATHS.observe(paths)
