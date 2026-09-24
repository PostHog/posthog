import datetime as dt
from collections.abc import Iterator
from typing import Any

from requests import Response, Session
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    DEFAULT_RETRY,
    make_tracked_session,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.depot.settings import (
    JOB_ATTEMPTS,
    PRIMARY_KEY,
    RUN_CREATED_AT,
)

JSONObject = dict[str, Any]

DEPOT_CI_SERVICE_URL = "https://api.depot.dev/depot.ci.v1.CIService"
REQUEST_TIMEOUT_SECONDS = 60
LIST_RUNS_PAGE_SIZE = 200
IN_FLIGHT_STATUSES = ["queued", "running"]
TERMINAL_STATUSES = ["finished", "failed", "cancelled"]
# Depot can leave a run in `queued` and never start it. An in-flight run older than this counts as
# stuck, so it does not hold the sync horizon back.
IN_FLIGHT_MAX_AGE = dt.timedelta(hours=6)

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
    parsed = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(value)
    return parsed.replace(tzinfo=dt.UTC) if parsed.tzinfo is None else parsed


def _list_runs(session: Session, repository: str, statuses: list[str]) -> Iterator[JSONObject]:
    body: JSONObject = {"repo": repository, "status": statuses, "pageSize": LIST_RUNS_PAGE_SIZE}
    while True:
        page = _call(session, "ListRuns", body)
        yield from page.get("runs", [])
        next_page_token = page.get("nextPageToken")
        if not next_page_token:
            return
        body = {**body, "pageToken": next_page_token}


# The sync only takes runs created before every recent in-flight run, so the watermark never passes
# a run that has not finished and each run is fetched once, after it is terminal. A job that is
# retried after its run was synced is therefore never picked up.
def _in_flight_horizon(session: Session, repository: str, now: dt.datetime) -> dt.datetime:
    in_flight_created_ats = [
        _parse_timestamp(run["createdAt"]) for run in _list_runs(session, repository, IN_FLIGHT_STATUSES)
    ]
    return min([now, *(created_at for created_at in in_flight_created_ats if created_at > now - IN_FLIGHT_MAX_AGE)])


def _run_ids_to_sync(
    session: Session, repository: str, created_after: dt.datetime | None, created_before: dt.datetime
) -> list[str]:
    runs: list[tuple[dt.datetime, str]] = []
    # ListRuns has no time filter but returns terminal runs newest first, so the walk stops at the
    # first run at or before the lower bound.
    for run in _list_runs(session, repository, TERMINAL_STATUSES):
        created_at = _parse_timestamp(run["createdAt"])
        if created_after is not None and created_at <= created_after:
            break
        if created_at < created_before:
            runs.append((created_at, run["runId"]))
    return [run_id for _, run_id in sorted(runs)]


def _run_columns(run: JSONObject) -> JSONObject:
    return {
        "run_id": run.get("runId"),
        "repo": run.get("repo"),
        "ref": run.get("ref"),
        "sha": run.get("sha"),
        "head_sha": run.get("headSha"),
        "trigger": run.get("trigger"),
        "run_status": run.get("status"),
        "run_created_at": run.get("createdAt"),
        "run_started_at": run.get("startedAt"),
        "run_finished_at": run.get("finishedAt"),
    }


def _workflow_columns(workflow: JSONObject) -> JSONObject:
    return {
        "workflow_id": workflow.get("workflowId"),
        "workflow_name": workflow.get("name"),
        "workflow_path": workflow.get("workflowPath"),
        "workflow_status": workflow.get("status"),
        "workflow_created_at": workflow.get("createdAt"),
        "workflow_started_at": workflow.get("startedAt"),
        "workflow_finished_at": workflow.get("finishedAt"),
    }


def _job_columns(job: JSONObject, display_name: str | None) -> JSONObject:
    return {
        "job_id": job.get("jobId"),
        "job_key": job.get("jobKey"),
        "job_display_name": display_name,
        "job_status": job.get("status"),
        "job_conclusion": job.get("conclusion"),
        "job_created_at": job.get("createdAt"),
        "job_started_at": job.get("startedAt"),
        "job_finished_at": job.get("finishedAt"),
    }


def _attempt_columns(attempt: JSONObject) -> JSONObject:
    return {
        "attempt_id": attempt.get("attemptId"),
        "attempt": attempt.get("attempt"),
        "attempt_status": attempt.get("status"),
        "attempt_conclusion": attempt.get("conclusion"),
        "attempt_created_at": attempt.get("createdAt"),
        "attempt_started_at": attempt.get("startedAt"),
        "attempt_finished_at": attempt.get("finishedAt"),
        "sandbox_id": attempt.get("sandboxId"),
    }


def _attempt_rows(run_metrics: JSONObject, run_status: JSONObject) -> list[JSONObject]:
    # GetRunStatus is the only RPC that returns a job's display name.
    display_names: dict[str, str | None] = {
        job["jobId"]: job.get("jobDisplayName")
        for workflow in run_status.get("workflows", [])
        for job in workflow.get("jobs", [])
    }
    run_columns = _run_columns(run_metrics["run"])
    rows: list[JSONObject] = []
    for workflow_metrics in run_metrics.get("workflows", []):
        workflow_columns = _workflow_columns(workflow_metrics["workflow"])
        for job_metrics in workflow_metrics.get("jobs", []):
            job = job_metrics["job"]
            job_columns = _job_columns(job, display_names.get(job.get("jobId")))
            for attempt_metrics in job_metrics.get("attempts", []):
                rows.append(
                    {**run_columns, **workflow_columns, **job_columns, **_attempt_columns(attempt_metrics["attempt"])}
                )
    return rows


def depot_source(
    api_token: str,
    repository: str,
    created_after: dt.datetime | str | None,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    lower_bound = _parse_timestamp(created_after) if created_after is not None else None

    def items() -> Iterator[list[JSONObject]]:
        session = _make_session(api_token)
        horizon = _in_flight_horizon(session, repository, dt.datetime.now(dt.UTC))
        run_ids = _run_ids_to_sync(session, repository, lower_bound, horizon)
        logger.info(
            "depot_ci.runs_to_sync",
            run_count=len(run_ids),
            created_after=lower_bound.isoformat() if lower_bound else None,
            created_before=horizon.isoformat(),
        )
        for run_id in run_ids:
            run_ref = {"runId": run_id}
            rows = _attempt_rows(_call(session, "GetRunMetrics", run_ref), _call(session, "GetRunStatus", run_ref))
            if rows:
                yield rows

    return SourceResponse(
        name=JOB_ATTEMPTS,
        items=items,
        primary_keys=[PRIMARY_KEY],
        partition_mode="datetime",
        partition_keys=[RUN_CREATED_AT],
        sort_mode="asc",
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
