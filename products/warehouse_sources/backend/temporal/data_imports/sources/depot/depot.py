import datetime as dt
from collections.abc import Iterator
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
    JOB_ATTEMPTS,
    PRIMARY_KEY,
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
# Depot can leave a run queued or running forever. A real run can take hours, but a real queued run
# starts in minutes, so past these ages an in-flight run counts as stuck.
IN_FLIGHT_MAX_AGE = {"queued": dt.timedelta(hours=6), "running": dt.timedelta(hours=24)}
IN_FLIGHT_STATUSES = list(IN_FLIGHT_MAX_AGE)

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


# The watermark stays behind every run still going, because a run it passed is never read. A stuck run
# with no workflows is the exception: it can never produce rows, and holding for it would stop every
# sync. A job retried after its run synced is not read again.
def _in_flight_horizon(
    session: Session, repository: str, now: dt.datetime, logger: FilteringBoundLogger
) -> dt.datetime:
    horizon = now
    for created_at, run in _list_runs(session, repository, IN_FLIGHT_STATUSES):
        if created_at < now - IN_FLIGHT_MAX_AGE.get(run["status"], IN_FLIGHT_MAX_AGE["queued"]):
            if not _call(session, "GetRunStatus", {"runId": run["runId"]}).get("workflows"):
                continue
            logger.warning("depot_ci.stuck_run_holds_horizon", run_id=run["runId"], created_at=created_at.isoformat())
        horizon = min(horizon, created_at)
    return horizon


def _runs_to_sync(
    session: Session, repository: str, created_after: dt.datetime | None, created_before: dt.datetime
) -> list[JSONObject]:
    # Depot stamps runs in whole seconds, and a sync that stopped partway through a second saved it as
    # the watermark, so that second is read again. The merge on attempt_id drops the repeats.
    runs = _list_runs(session, repository, TERMINAL_STATUSES, created_after)
    return [run for created_at, run in runs if created_at < created_before]


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


def depot_source(
    api_token: str,
    repository: str,
    created_after: dt.datetime | str | None,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    lower_bound = _parse_timestamp(created_after) if created_after is not None else None

    def items() -> Iterator[list[JSONObject]]:
        session = _make_session(api_token)
        horizon = _in_flight_horizon(session, repository, dt.datetime.now(dt.UTC), logger)
        runs = _runs_to_sync(session, repository, lower_bound, horizon)
        logger.info(
            "depot_ci.runs_to_sync",
            run_count=len(runs),
            created_after=lower_bound.isoformat() if lower_bound else None,
            created_before=horizon.isoformat(),
        )
        for run in runs:
            rows = _run_attempt_rows(session, run)
            if rows:
                yield rows

    return SourceResponse(
        name=JOB_ATTEMPTS,
        items=items,
        primary_keys=[PRIMARY_KEY],
        partition_mode="datetime",
        partition_format="week",
        partition_keys=[RUN_CREATED_AT],
        sort_mode="asc",
        # The watermark saves per chunk, and the default chunk holds a whole first sync of a busy repository.
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
