import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.skyvern.settings import (
    SKYVERN_ENDPOINTS,
    SkyvernEndpointConfig,
)

SKYVERN_DEFAULT_BASE_URL = "https://api.skyvern.com"

# Every paginated list endpoint accepts page/page_size. 100 is the documented max for /v1/runs and a
# safe ceiling for the others (their only documented bound is a minimum of 1).
PAGE_SIZE = 100

# Bound per-workflow paging on incremental syncs so a huge run history can't scan unbounded. 100 pages
# * 100 rows = 10k runs per workflow within the created_at_start window. Full refreshes ignore this cap
# (see _get_fan_out_rows) so a workflow's older runs are never permanently truncated.
MAX_PAGES_PER_WORKFLOW = 100


class SkyvernRetryableError(Exception):
    pass


@dataclasses.dataclass
class SkyvernResumeConfig:
    # Next page number to fetch (1-based).
    page: int = 1
    # For the runs fan-out: the workflow currently being paged. A stable workflow_permanent_id
    # bookmark (not a positional index) so workflows added/removed between a crash and the retry can't
    # resume us into the wrong workflow. None for the standard (non-fan-out) endpoints.
    workflow_permanent_id: Optional[str] = None


def _base_url(base_url: str | None) -> str:
    return (base_url or SKYVERN_DEFAULT_BASE_URL).rstrip("/")


def _get_headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key, "Accept": "application/json"}


def _format_datetime_z(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC, which Skyvern's created_at_start filter expects."""
    utc_dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _to_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _created_at_start(
    config: SkyvernEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> str | None:
    """Build the created_at_start filter value from the incremental watermark.

    Subtracts the endpoint's lookback and clamps to now (a future-dated cursor would filter out every
    row). The re-pulled window is deduped by merge on the primary key.
    """
    if not (should_use_incremental_field and config.supports_incremental and db_incremental_field_last_value):
        return None
    dt = _to_datetime(db_incremental_field_last_value)
    if dt is None:
        return None
    if config.incremental_lookback:
        dt = dt - config.incremental_lookback
    now = datetime.now(UTC)
    aware = dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    if aware > now:
        dt = now
    return _format_datetime_z(dt)


@retry(
    retry=retry_if_exception_type(
        (
            SkyvernRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, params: dict[str, Any], headers: dict[str, str], logger: FilteringBoundLogger
) -> Any:
    full_url = f"{url}?{urlencode(params)}" if params else url
    response = session.get(full_url, headers=headers, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise SkyvernRetryableError(f"Skyvern API error (retryable): status={response.status_code}, url={full_url}")

    if not response.ok:
        logger.error(f"Skyvern API error: status={response.status_code}, body={response.text}, url={full_url}")
        response.raise_for_status()

    return response.json()


def _extract_items(data: Any, data_key: str | None) -> list[dict[str, Any]]:
    """A Skyvern list response is either a bare array or an object wrapping the rows under `data_key`."""
    if data_key is not None:
        if isinstance(data, dict):
            items = data.get(data_key) or []
            return items if isinstance(items, list) else []
        return []
    return data if isinstance(data, list) else []


def validate_credentials(api_key: str, base_url: str | None) -> tuple[bool, str | None]:
    """Probe the cheapest list endpoint to confirm the API key is genuine."""
    url = f"{_base_url(base_url)}/v1/agents"
    try:
        # base_url is user-supplied, so treat it as an SSRF boundary: pin redirects off so a
        # malicious/self-hosted host can't bounce the API key to an internal address. The egress proxy
        # is the load-bearing control; this is defense-in-depth.
        response = make_tracked_session(allow_redirects=False).get(
            url, headers=_get_headers(api_key), params={"page": 1, "page_size": 1}, timeout=10
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid Skyvern API key"
    return False, f"Skyvern API returned status {response.status_code}"


def _iter_workflow_ids(
    session: requests.Session, base_url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[str]:
    """Page through /v1/agents (workflows only) and yield each workflow_permanent_id."""
    url = f"{base_url}/v1/agents"
    page = 1
    while True:
        data = _fetch_page(
            session, url, {"page": page, "page_size": PAGE_SIZE, "only_workflows": "true"}, headers, logger
        )
        items = _extract_items(data, None)
        if not items:
            break
        for item in items:
            wpid = item.get("workflow_permanent_id")
            if wpid:
                yield wpid
        if len(items) < PAGE_SIZE:
            break
        page += 1


def _get_simple_rows(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SkyvernResumeConfig],
    config: SkyvernEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if (resume and resume.page) else 1
    url = f"{base_url}{config.path}"

    while True:
        params = {"page": page, "page_size": PAGE_SIZE, **config.extra_params}
        data = _fetch_page(session, url, params, headers, logger)
        items = _extract_items(data, config.data_key)
        if not items:
            break

        yield items

        if len(items) < PAGE_SIZE:
            break
        page += 1
        # Save AFTER yielding so a crash re-fetches the last page rather than skipping it; merge
        # dedupes on the primary key.
        resumable_source_manager.save_state(SkyvernResumeConfig(page=page))


def _get_fan_out_rows(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SkyvernResumeConfig],
    config: SkyvernEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every workflow, pulling its runs from /v1/agents/{workflow_permanent_id}/runs.

    Incremental syncs bound each workflow's run list with created_at_start (watermark minus lookback).
    workflow_run_id is globally unique, so it is a sufficient primary key on its own.
    """
    created_at_start = _created_at_start(config, should_use_incremental_field, db_incremental_field_last_value)

    workflow_ids = list(_iter_workflow_ids(session, base_url, headers, logger))
    if not workflow_ids:
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_index = 0
    start_page = 1
    if resume is not None and resume.workflow_permanent_id in workflow_ids:
        start_index = workflow_ids.index(resume.workflow_permanent_id)
        start_page = resume.page or 1
        logger.debug(f"Skyvern: resuming runs fan-out from workflow={resume.workflow_permanent_id}, page={start_page}")

    for index in range(start_index, len(workflow_ids)):
        workflow_permanent_id = workflow_ids[index]
        page = start_page if index == start_index else 1
        url = f"{base_url}{config.path.format(workflow_permanent_id=workflow_permanent_id)}"

        # A full refresh (no created_at_start window) must page through every run, or a workflow with
        # more than MAX_PAGES_PER_WORKFLOW * PAGE_SIZE runs would be permanently truncated: later
        # incremental syncs only fetch runs newer than the watermark, so the skipped older pages would
        # never be backfilled. The cap only guards runaway on incremental syncs, whose created_at_start
        # window already bounds the volume.
        while created_at_start is None or page <= MAX_PAGES_PER_WORKFLOW:
            params: dict[str, Any] = {"page": page, "page_size": PAGE_SIZE}
            if created_at_start:
                params["created_at_start"] = created_at_start
            data = _fetch_page(session, url, params, headers, logger)
            items = _extract_items(data, config.data_key)
            if not items:
                break

            yield items

            if len(items) < PAGE_SIZE:
                break
            page += 1
            resumable_source_manager.save_state(
                SkyvernResumeConfig(page=page, workflow_permanent_id=workflow_permanent_id)
            )
        else:
            logger.warning(
                "Skyvern: per-workflow incremental run page cap reached; some runs within the "
                "lookback window may be skipped until the next full refresh",
                workflow_permanent_id=workflow_permanent_id,
                max_pages=MAX_PAGES_PER_WORKFLOW,
            )

        # Advance the bookmark to the next workflow so a crash between workflows resumes correctly.
        if index + 1 < len(workflow_ids):
            resumable_source_manager.save_state(
                SkyvernResumeConfig(page=1, workflow_permanent_id=workflow_ids[index + 1])
            )


def get_rows(
    api_key: str,
    base_url: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SkyvernResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = SKYVERN_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    resolved_base_url = _base_url(base_url)
    # base_url is user-supplied — pin redirects off as an SSRF boundary so a hostile host can't
    # redirect the credentialed request to an internal address (see validate_credentials).
    session = make_tracked_session(allow_redirects=False)

    if config.fan_out_over_workflows:
        yield from _get_fan_out_rows(
            session,
            resolved_base_url,
            headers,
            logger,
            resumable_source_manager,
            config,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
        return

    yield from _get_simple_rows(session, resolved_base_url, headers, logger, resumable_source_manager, config)


def skyvern_source(
    api_key: str,
    base_url: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SkyvernResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = SKYVERN_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            base_url=base_url,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Skyvern list endpoints return newest-first and expose no sort param, so rows arrive
        # descending by created_at. In desc mode the pipeline persists the incremental watermark only
        # at successful job end, which is what we want for the runs fan-out: a partial run's max
        # created_at says nothing about workflows it never reached.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
