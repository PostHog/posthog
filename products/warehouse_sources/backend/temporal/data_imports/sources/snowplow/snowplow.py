import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.snowplow.settings import (
    SNOWPLOW_ENDPOINTS,
    SnowplowEndpointConfig,
)

SNOWPLOW_BASE_URL = "https://console.snowplowanalytics.com/api/msc/v1"

# The jobs API only retains runs for about the preceding week and rejects windows outside it;
# the small margin keeps the clamped `from` inside the allowed range while requests are in flight.
JOB_RUNS_RETENTION = timedelta(days=7) - timedelta(minutes=10)
# Query windows are capped at 96 hours by the API; 24h slices stay well under that and bound the
# per-window 10,000-row result cap.
JOB_RUNS_WINDOW = timedelta(hours=24)
# The jobs API caps a window's results at 10,000 rows with no pagination; a full window means
# rows were probably dropped.
JOB_RUNS_WINDOW_ROW_CAP = 10_000
# Re-pull a trailing window each incremental run: a run listed while RUNNING changes state (and a
# recent failed-events bucket keeps accumulating) after we first fetch it. Merge dedupes the
# re-pulled rows on the primary key.
INCREMENTAL_LOOKBACK = timedelta(hours=24)
# GET /data-structures/v1 pages with from/size offset params.
DATA_STRUCTURES_PAGE_SIZE = 100
# Bound the offset paginator so a misbehaving API can't loop forever.
DATA_STRUCTURES_MAX_PAGES = 1000


class SnowplowRetryableError(Exception):
    pass


class SnowplowAuthError(Exception):
    """Credential problem (bad org ID, key ID, or key) — permanent, never retried."""


@dataclasses.dataclass
class SnowplowResumeConfig:
    # End of the last fully-yielded time window (ISO 8601) for the windowed jobs endpoints. The
    # resumed attempt restarts from here; the in-flight window is re-fetched and merge dedupes.
    window_from: str | None = None
    # Pipeline UUIDs already fully processed in an earlier attempt of the failed-events fan-out.
    # Keyed on stable IDs (not a positional index) so a pipeline added between a crash and the
    # retry is still processed rather than skipped.
    completed_pipeline_ids: list[str] = dataclasses.field(default_factory=list)


def _format_datetime(dt: datetime) -> str:
    """Format as the Z-suffixed ISO 8601 the API documents; from/to must share one format."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _iter_windows(start: datetime, end: datetime, step: timedelta) -> Iterator[tuple[datetime, datetime]]:
    window_start = start
    while window_start < end:
        window_end = min(window_start + step, end)
        yield window_start, window_end
        window_start = window_end


class SnowplowClient:
    """Console API client handling the two-step auth: the API key + key ID mint a JWT
    (valid ~24h) which authenticates every data request; a mid-sync 401 re-mints it once."""

    def __init__(self, organization_id: str, api_key_id: str, api_key: str, logger: FilteringBoundLogger) -> None:
        self._organization_id = organization_id
        self._api_key_id = api_key_id
        self._api_key = api_key
        self._logger = logger
        # One session reused across every request so urllib3 keeps the connection alive. Register
        # the API key for value-based redaction and disable sample capture: responses carry
        # customer data (user emails, schema definitions, job metadata) and the token exchange
        # returns a bearer token in the body, neither of which may reach the HTTP sample bucket.
        self._session = make_tracked_session(redact_values=(api_key,), capture=False)
        self._access_token: str | None = None

    @property
    def _org_base_url(self) -> str:
        return f"{SNOWPLOW_BASE_URL}/organizations/{self._organization_id}"

    @retry(
        retry=retry_if_exception_type(
            (
                SnowplowRetryableError,
                requests.ReadTimeout,
                requests.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            )
        ),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def _mint_token(self) -> str:
        url = f"{self._org_base_url}/credentials/v3/token"
        response = self._session.get(
            url,
            headers={"X-API-Key-Id": self._api_key_id, "X-API-Key": self._api_key},
            timeout=30,
        )
        if response.status_code == 429 or response.status_code >= 500:
            raise SnowplowRetryableError(f"Snowplow token endpoint error (retryable): status={response.status_code}")
        if response.status_code in (401, 403):
            raise SnowplowAuthError(
                "Snowplow API authentication failed: the API key or API key ID is invalid or has been revoked."
            )
        # The token endpoint 404s when the organization ID doesn't exist.
        if response.status_code == 404:
            raise SnowplowAuthError(
                "Snowplow API authentication failed: no organization found with this organization ID."
            )
        response.raise_for_status()
        token = response.json().get("accessToken")
        if not token:
            raise SnowplowAuthError("Snowplow API authentication failed: the token response had no access token.")
        return token

    @retry(
        retry=retry_if_exception_type(
            (
                SnowplowRetryableError,
                requests.ReadTimeout,
                requests.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            )
        ),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def _request(self, path: str, params: Optional[dict[str, Any]]) -> requests.Response:
        response = self._session.get(
            f"{self._org_base_url}{path}",
            headers={"Authorization": f"Bearer {self._access_token}", "Accept": "application/json"},
            params=params,
            timeout=60,
        )
        if response.status_code == 429 or response.status_code >= 500:
            raise SnowplowRetryableError(f"Snowplow API error (retryable): status={response.status_code}, path={path}")
        return response

    def get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        if self._access_token is None:
            self._access_token = self._mint_token()
        response = self._request(path, params)
        if response.status_code == 401:
            # The JWT expired mid-sync (24h validity) — re-mint once and retry the request.
            self._access_token = self._mint_token()
            response = self._request(path, params)
        if not response.ok:
            # Log only status and path — never the response body, which can echo customer data.
            self._logger.error(f"Snowplow API error: status={response.status_code}, path={path}")
            response.raise_for_status()
        return response.json()


def validate_credentials(
    organization_id: str, api_key_id: str, api_key: str, logger: FilteringBoundLogger
) -> tuple[bool, str | None]:
    """Probe the credentials by minting a token — one cheap call validating all three inputs."""
    client = SnowplowClient(organization_id, api_key_id, api_key, logger)
    try:
        client._mint_token()
        return True, None
    except SnowplowAuthError as e:
        return False, str(e)
    except Exception:
        return False, "Could not reach the Snowplow Console API. Check the credentials and try again."


def _jobs_window_bounds(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    resume_window_from: str | None,
    now: datetime,
) -> tuple[datetime, datetime]:
    """Compute the overall (from, to) range to slice for the jobs endpoints.

    Runs are only retained for about a week, so both first syncs and stale watermarks clamp to
    the retention floor — deeper backfill is not possible.
    """
    floor = now - JOB_RUNS_RETENTION
    if resume_window_from is not None:
        start = _parse_datetime(resume_window_from)
    elif should_use_incremental_field and db_incremental_field_last_value:
        start = _parse_datetime(db_incremental_field_last_value) - INCREMENTAL_LOOKBACK
    else:
        start = floor
    start = max(start, floor)
    if start > now:
        start = now
    return start, now


def _get_windowed_job_rows(
    client: SnowplowClient,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SnowplowResumeConfig],
    config: SnowplowEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start, end = _jobs_window_bounds(
        should_use_incremental_field,
        db_incremental_field_last_value,
        resume.window_from if resume else None,
        now=datetime.now(UTC),
    )

    for window_start, window_end in _iter_windows(start, end, JOB_RUNS_WINDOW):
        runs = client.get(
            "/jobs/v1/runs", params={"from": _format_datetime(window_start), "to": _format_datetime(window_end)}
        )
        if not isinstance(runs, list):
            runs = []
        if len(runs) >= JOB_RUNS_WINDOW_ROW_CAP:
            logger.warning(
                f"Snowplow: jobs window {_format_datetime(window_start)}..{_format_datetime(window_end)} returned "
                f"{len(runs)} rows — the API caps a window at {JOB_RUNS_WINDOW_ROW_CAP} rows, data may be truncated"
            )

        if config.fan_out_over_runs:
            yield from _get_step_rows_for_runs(client, logger, runs)
        elif runs:
            yield runs

        # Save AFTER the window's batches were consumed, so a crash re-fetches the in-flight
        # window (merge dedupes on the primary key) rather than skipping it.
        resumable_source_manager.save_state(SnowplowResumeConfig(window_from=_format_datetime(window_end)))


def _get_step_rows_for_runs(
    client: SnowplowClient, logger: FilteringBoundLogger, runs: list[dict[str, Any]]
) -> Iterator[list[dict[str, Any]]]:
    for run in runs:
        run_id = run.get("runId")
        if not run_id:
            # runId is part of the (runId, name) primary key; a null-keyed row would collapse
            # steps from every such run into one persisted row, so skip it.
            logger.warning("Snowplow: skipping job run without a runId in the steps fan-out")
            continue
        try:
            steps = client.get(f"/jobs/v1/runs/{run_id}/steps")
        except requests.HTTPError as exc:
            # A run that aged out of retention between the window listing and this fetch 404s;
            # its steps are genuinely gone, so skip it rather than failing the whole sync.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Snowplow: job run {run_id} not found while fetching steps, skipping")
                continue
            raise
        rows = [
            {
                **step,
                "runId": run_id,
                "jobId": run.get("jobId"),
                "jobName": run.get("jobName"),
                "environment": run.get("environment"),
                "runStartTime": run.get("startTime"),
            }
            for step in steps
            if isinstance(step, dict) and step.get("name")
        ]
        if rows:
            yield rows


def _flatten_failed_event_aggregates(
    pipeline_id: str, aggregates: list[dict[str, Any]], logger: FilteringBoundLogger
) -> list[dict[str, Any]]:
    """Flatten each aggregate's per-bucket metrics into one row per (pipeline, error, window)."""
    rows: list[dict[str, Any]] = []
    for aggregate in aggregates:
        error_id = aggregate.get("errorId")
        if not error_id:
            # errorId is part of the primary key; a null-keyed row would collapse every such
            # aggregate for the pipeline into one persisted row, so skip it.
            logger.warning(f"Snowplow: skipping failed-event aggregate without an errorId for pipeline {pipeline_id}")
            continue
        for point in aggregate.get("metrics") or []:
            if not isinstance(point, dict) or not point.get("window"):
                continue
            rows.append(
                {
                    "pipelineId": pipeline_id,
                    "errorId": error_id,
                    "schemaKey": aggregate.get("schemaKey"),
                    "classification": aggregate.get("classification"),
                    "window": point.get("window"),
                    "count": point.get("count"),
                    "lastSeen": point.get("lastSeen"),
                }
            )
    return rows


def _get_failed_event_metric_rows(
    client: SnowplowClient,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SnowplowResumeConfig],
    config: SnowplowEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    now = datetime.now(UTC)
    if should_use_incremental_field and db_incremental_field_last_value:
        start = _parse_datetime(db_incremental_field_last_value) - INCREMENTAL_LOOKBACK
    else:
        # The metrics store keeps about a week of failed-event aggregates (the API's own default
        # range is the preceding week), so that is the deepest useful first sync.
        start = now - JOB_RUNS_RETENTION
    if start > now:
        start = now
    params = {"from": _format_datetime(start), "to": _format_datetime(now)}

    pipelines = client.get("/pipelines/v1")
    pipeline_list = pipelines.get("pipelines", []) if isinstance(pipelines, dict) else []

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    completed_pipeline_ids = list(resume.completed_pipeline_ids) if resume is not None else []
    completed = set(completed_pipeline_ids)

    for pipeline in pipeline_list:
        pipeline_id = pipeline.get("id")
        if not pipeline_id or pipeline_id in completed:
            continue
        aggregates = client.get(config.path.format(pipelineId=pipeline_id), params=params)
        if not isinstance(aggregates, list):
            aggregates = []
        rows = _flatten_failed_event_aggregates(pipeline_id, aggregates, logger)
        if rows:
            yield rows

        # Mark this pipeline done AFTER its rows were consumed, so a crash mid-pipeline
        # re-processes it (merge dedupes) rather than skipping it.
        completed_pipeline_ids.append(pipeline_id)
        completed.add(pipeline_id)
        resumable_source_manager.save_state(SnowplowResumeConfig(completed_pipeline_ids=list(completed_pipeline_ids)))


def _get_list_rows(
    client: SnowplowClient, logger: FilteringBoundLogger, endpoint: str, config: SnowplowEndpointConfig
) -> Iterator[list[dict[str, Any]]]:
    if endpoint == "data_structures":
        offset = 0
        for _ in range(DATA_STRUCTURES_MAX_PAGES):
            page = client.get(config.path, params={"from": offset, "size": DATA_STRUCTURES_PAGE_SIZE})
            items = page if isinstance(page, list) else []
            if items:
                yield items
            if len(items) < DATA_STRUCTURES_PAGE_SIZE:
                return
            offset += len(items)
        logger.warning(
            f"Snowplow: data_structures hit the page cap ({DATA_STRUCTURES_MAX_PAGES}), data may be truncated"
        )
        return

    data = client.get(config.path)
    if config.data_key is not None:
        items = data.get(config.data_key, []) if isinstance(data, dict) else []
    else:
        items = data if isinstance(data, list) else []
    if items:
        yield items


def get_rows(
    organization_id: str,
    api_key_id: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SnowplowResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = SNOWPLOW_ENDPOINTS[endpoint]
    client = SnowplowClient(organization_id, api_key_id, api_key, logger)

    if config.windowed:
        yield from _get_windowed_job_rows(
            client,
            logger,
            resumable_source_manager,
            config,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    elif config.fan_out_over_pipelines:
        yield from _get_failed_event_metric_rows(
            client,
            logger,
            resumable_source_manager,
            config,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    else:
        yield from _get_list_rows(client, logger, endpoint, config)


def snowplow_source(
    organization_id: str,
    api_key_id: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SnowplowResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SNOWPLOW_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            organization_id=organization_id,
            api_key_id=api_key_id,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # Incremental endpoints persist the watermark only at successful job end (desc mode): the
        # API documents no intra-window ordering, and fan-out partial runs say nothing about
        # parents they never reached, so per-batch persistence could advance the watermark past
        # rows a crashed run still owes.
        sort_mode="desc" if config.incremental_fields else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
