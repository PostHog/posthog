import datetime as dt
from collections.abc import Callable, Iterator
from typing import Any

from requests import Response, Session
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    DEFAULT_RETRY,
    make_tracked_session,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.depot.settings import (
    ARTIFACTS,
    FAILURE_DIAGNOSES,
    JOB_ATTEMPTS,
    JOB_METRICS,
    PRIMARY_KEYS,
    RUN_CREATED_AT,
)

JSONObject = dict[str, Any]

DEPOT_CI_SERVICE_URL = "https://api.depot.dev/depot.ci.v1.CIService"
REQUEST_TIMEOUT_SECONDS = 60
# When a ListRuns page ends inside a second, the next page skips that second's other runs. A walk with
# another page size ends its pages elsewhere and returns most of them; a run both walks skip is lost
# until Depot fixes its cursor. Depot caps pages at 100.
LIST_RUNS_PAGE_SIZES = (100, 57)
TERMINAL_STATUSES = ["finished", "failed", "cancelled"]
# A finished run has no failed or cancelled job left to diagnose.
DIAGNOSED_RUN_STATUSES = frozenset({"failed", "cancelled"})
LIST_ARTIFACTS_PAGE_SIZE = 500
# Connect sends every RPC as a POST. Every RPC this source calls is a read, so a retry is as safe as
# a retried GET.
_DEPOT_RETRY = DEFAULT_RETRY.new(allowed_methods=frozenset(DEFAULT_RETRY.allowed_methods or ()) | {"POST"})


def _make_session(api_token: str) -> Session:
    return make_tracked_session(
        headers={"Authorization": f"Bearer {api_token}"},
        retry=_DEPOT_RETRY,
        redact_values=(api_token,),
    )


def _post(session: Session, method: str, body: JSONObject) -> Response:
    return session.post(f"{DEPOT_CI_SERVICE_URL}/{method}", json=body, timeout=REQUEST_TIMEOUT_SECONDS)


def _call(session: Session, method: str, body: JSONObject) -> JSONObject:
    response = _post(session, method, body)
    response.raise_for_status()
    return response.json()


def _parse_timestamp(value: dt.datetime | str) -> dt.datetime:
    parsed = parse_datetime_value(value)
    if parsed is None:
        raise ValueError(f"Depot returned an unparseable timestamp: {value!r}")
    return parsed


def _walk_runs(session: Session, repository: str, statuses: list[str], page_size: int) -> Iterator[JSONObject]:
    body: JSONObject = {"repo": repository, "status": statuses, "pageSize": page_size}
    while True:
        page = _call(session, "ListRuns", body)
        yield from page.get("runs", [])
        next_page_token = page.get("nextPageToken")
        if not next_page_token:
            return
        body = {**body, "pageToken": next_page_token}


def _list_runs(
    session: Session, repository: str, statuses: list[str], created_after: dt.datetime | None = None
) -> list[tuple[dt.datetime, JSONObject]]:
    """Oldest first. ListRuns has no time filter, but it lists newest first, so each walk stops at the
    first run older than ``created_after``. The second walk's copy of a run wins, as the fresher status."""
    runs: dict[str, tuple[dt.datetime, JSONObject]] = {}
    for page_size in LIST_RUNS_PAGE_SIZES:
        listed = 0
        for run in _walk_runs(session, repository, statuses, page_size):
            created_at = _parse_timestamp(run["createdAt"])
            if created_after is not None and created_at < created_after:
                break
            runs[run["runId"]] = (created_at, run)
            listed += 1
        if listed < page_size:
            # No page end inside the listing, so nothing was skipped.
            break
    return sorted(runs.values(), key=lambda entry: (entry[0], entry[1]["runId"]))


def _attempt_rows(run: JSONObject, workflow: JSONObject, run_workflow_count: int) -> list[JSONObject]:
    shared_columns = {
        "run_id": run["runId"],
        "run_workflow_count": run_workflow_count,
        "repo": workflow.get("repo"),
        "ref": workflow.get("ref"),
        "sha": workflow.get("sha"),
        "head_sha": workflow.get("headSha"),
        "trigger": workflow.get("trigger"),
        "run_status": workflow.get("runStatus"),
        # The listing's value, so the incremental cursor stays in the clock the listing walk compares.
        "run_created_at": run["createdAt"],
        "run_started_at": workflow.get("runStartedAt"),
        "run_finished_at": workflow.get("runFinishedAt"),
        "workflow_id": workflow["workflowId"],
        "workflow_name": workflow.get("workflowName"),
        "workflow_path": workflow.get("workflowPath"),
        "workflow_status": workflow.get("workflowStatus"),
        "workflow_created_at": workflow.get("workflowCreatedAt"),
        "workflow_started_at": workflow.get("workflowStartedAt"),
        "workflow_finished_at": workflow.get("workflowFinishedAt"),
    }
    rows: list[JSONObject] = []
    for job in workflow.get("jobs", []):
        job_columns = {
            "job_id": job["jobId"],
            "job_key": job.get("jobKey"),
            "job_display_name": job.get("jobDisplayName"),
            "job_status": job.get("status"),
            "job_started_at": job.get("startedAt"),
            "job_finished_at": job.get("finishedAt"),
        }
        for attempt in job.get("attempts", []):
            rows.append(
                {
                    **shared_columns,
                    **job_columns,
                    "attempt_id": attempt["attemptId"],
                    "attempt": attempt.get("attempt"),
                    "attempt_status": attempt.get("status"),
                    "attempt_started_at": attempt.get("startedAt"),
                    "attempt_finished_at": attempt.get("finishedAt"),
                    "sandbox_id": attempt.get("sandboxId"),
                }
            )
    return rows


def _run_attempt_rows(session: Session, run: JSONObject) -> list[JSONObject]:
    # GetRunMetrics would answer in one call, but Depot refuses it with ResourceExhausted for a run
    # with many attempts. GetWorkflow answers for any workflow size, so the run is read per workflow.
    workflows = _call(session, "GetRunStatus", {"runId": run["runId"]}).get("workflows", [])
    return [
        row
        for workflow in workflows
        for row in _attempt_rows(
            run, _call(session, "GetWorkflow", {"workflowId": workflow["workflowId"]}), len(workflows)
        )
    ]


def _int_or_none(value: int | str | None) -> int | None:
    # Connect encodes int64 fields as JSON strings.
    return int(value) if value is not None and value != "" else None


def _run_job_metrics_batches(session: Session, run: JSONObject) -> Iterator[list[JSONObject]]:
    # GetRunMetrics fails with ResourceExhausted for a run with many attempts, so metrics are read per job.
    workflows = _call(session, "GetRunStatus", {"runId": run["runId"]}).get("workflows", [])
    for workflow in workflows:
        for job in workflow.get("jobs", []):
            if not job.get("attempts"):
                continue
            metrics = _call(session, "GetJobMetrics", {"jobId": job["jobId"]})
            workflow_context = metrics.get("workflow") or {}
            job_context = metrics.get("job") or {}
            shared_columns = {
                "run_id": run["runId"],
                "run_created_at": run["createdAt"],
                "workflow_id": workflow["workflowId"],
                "workflow_name": workflow_context.get("name"),
                "workflow_path": workflow_context.get("workflowPath"),
                "job_id": job["jobId"],
                "job_key": job_context.get("jobKey"),
                "job_status": job_context.get("status"),
                "job_conclusion": job_context.get("conclusion"),
                "snapshot_at": metrics.get("snapshotAt"),
            }
            rows: list[JSONObject] = []
            for summary in metrics.get("attempts", []):
                attempt = summary.get("attempt") or {}
                availability = summary.get("availability") or {}
                stats = summary.get("stats") or {}
                rows.append(
                    {
                        **shared_columns,
                        "attempt_id": attempt["attemptId"],
                        "attempt": attempt.get("attempt"),
                        "attempt_status": attempt.get("status"),
                        "attempt_conclusion": attempt.get("conclusion"),
                        "attempt_started_at": attempt.get("startedAt"),
                        "attempt_finished_at": attempt.get("finishedAt"),
                        "sandbox_id": attempt.get("sandboxId"),
                        "availability": availability.get("reason"),
                        "sample_count": stats.get("sampleCount"),
                        "peak_cpu_utilization": stats.get("peakCpuUtilization"),
                        "average_cpu_utilization": stats.get("averageCpuUtilization"),
                        "peak_memory_utilization": stats.get("peakMemoryUtilization"),
                        "average_memory_utilization": stats.get("averageMemoryUtilization"),
                        "peak_memory_usage_bytes": _int_or_none(stats.get("peakMemoryUsageBytes")),
                        "average_memory_usage_bytes": stats.get("averageMemoryUsageBytes"),
                        "observed_started_at": stats.get("observedStartedAt"),
                        "observed_finished_at": stats.get("observedFinishedAt"),
                    }
                )
            if rows:
                yield rows


def _run_artifact_batches(session: Session, run: JSONObject) -> Iterator[list[JSONObject]]:
    body: JSONObject = {"runId": run["runId"], "pageSize": LIST_ARTIFACTS_PAGE_SIZE}
    while True:
        page = _call(session, "ListArtifacts", body)
        rows = [
            {
                "artifact_id": artifact["artifactId"],
                "run_id": run["runId"],
                "run_created_at": run["createdAt"],
                "workflow_id": artifact.get("workflowId"),
                "workflow_path": artifact.get("workflowPath"),
                "job_id": artifact.get("jobId"),
                "job_key": artifact.get("jobKey"),
                "attempt_id": artifact.get("attemptId"),
                "attempt": artifact.get("attempt"),
                "name": artifact.get("name"),
                "size_bytes": _int_or_none(artifact.get("sizeBytes")),
                "created_at": artifact.get("createdAt"),
            }
            for artifact in page.get("artifacts", [])
        ]
        if rows:
            yield rows
        next_page_token = page.get("nextPageToken")
        if not next_page_token:
            return
        body = {**body, "pageToken": next_page_token}


def _run_failure_diagnosis_batches(session: Session, run: JSONObject) -> Iterator[list[JSONObject]]:
    if run.get("status") not in DIAGNOSED_RUN_STATUSES:
        return
    diagnosis = _call(
        session,
        "GetFailureDiagnosis",
        {"targetId": run["runId"], "targetType": "FAILURE_DIAGNOSIS_TARGET_TYPE_RUN"},
    )
    rows = [
        {
            "run_id": run["runId"],
            "run_created_at": run["createdAt"],
            "run_status": run.get("status"),
            "fingerprint": group["fingerprint"],
            "source": group.get("source"),
            "count": group.get("count"),
            "error_message": group.get("errorMessage"),
            "error_message_truncated": group.get("errorMessageTruncated"),
            "diagnosis": group.get("diagnosis"),
            "possible_fix": group.get("possibleFix"),
            "representatives": group.get("representatives", []),
            "omitted_representative_count": group.get("omittedRepresentativeCount"),
        }
        for group in diagnosis.get("failureGroups", [])
    ]
    if rows:
        yield rows


def _run_job_attempt_batches(session: Session, run: JSONObject) -> Iterator[list[JSONObject]]:
    rows = _run_attempt_rows(session, run)
    if rows:
        yield rows


_RUN_BATCHES: dict[str, Callable[[Session, JSONObject], Iterator[list[JSONObject]]]] = {
    JOB_ATTEMPTS: _run_job_attempt_batches,
    JOB_METRICS: _run_job_metrics_batches,
    ARTIFACTS: _run_artifact_batches,
    FAILURE_DIAGNOSES: _run_failure_diagnosis_batches,
}


def depot_source(
    api_token: str,
    repository: str,
    created_after: dt.datetime | str | None,
    logger: FilteringBoundLogger,
    on_complete: Callable[[], None] | None = None,
    endpoint: str = JOB_ATTEMPTS,
) -> SourceResponse:
    run_batches = _RUN_BATCHES[endpoint]
    lower_bound = _parse_timestamp(created_after) if created_after is not None else None

    def items() -> Iterator[list[JSONObject]]:
        session = _make_session(api_token)
        # Newest first, so a sync that stops partway has already stored the runs that no earlier sync read.
        runs = [run for _, run in reversed(_list_runs(session, repository, TERMINAL_STATUSES, lower_bound))]
        logger.info(
            "depot_ci.runs_to_sync",
            endpoint=endpoint,
            run_count=len(runs),
            created_after=lower_bound.isoformat() if lower_bound else None,
        )
        for run in runs:
            yield from run_batches(session, run)
        if on_complete is not None:
            on_complete()

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=PRIMARY_KEYS[endpoint],
        partition_mode="datetime",
        partition_format="week",
        partition_keys=[RUN_CREATED_AT],
        # Descending defers the watermark save to the end of the sync, so a replay that stops partway cannot move it back.
        sort_mode="desc",
        # Rows become durable per chunk, and the default chunk holds a whole first sync of a busy repository.
        chunk_size=5_000,
    )


def validate_credentials(api_token: str, repository: str) -> tuple[bool, str | None]:
    response = _post(_make_session(api_token), "ListRuns", {"repo": repository, "pageSize": 1})
    if response.status_code == 401:
        return False, "Depot didn't accept this API token. Check that you copied the whole token and try again."
    if response.status_code == 403:
        return (
            False,
            "This API token can't read Depot CI runs. Create an organization API token in your Depot organization settings and try again.",
        )
    if not response.ok:
        return (
            False,
            f"Couldn't list Depot CI runs for {repository} (HTTP {response.status_code}). Check the repository and try again.",
        )
    return True, None
