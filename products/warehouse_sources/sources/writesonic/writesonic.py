import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Optional
from urllib.parse import urljoin

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    make_tracked_session,
    retry_with_deadline,
)
from products.warehouse_sources.sources.writesonic.settings import (
    BASE_URL,
    CONTENT_OPTIMIZE_PAGES_PATH,
    DEFAULT_LOOKBACK_DAYS,
    PAGE_SIZE,
    WRITESONIC_ENDPOINTS,
    WritesonicEndpointConfig,
)

REQUEST_TIMEOUT = 60

# Let tenacity be the only retry layer so every request gets the same bounded budget.
NO_URLLIB_RETRY = Retry(total=0)

# Upper bound on how long we'll honor a server-provided `Retry-After`, so a large (or hostile)
# value can't pin a worker thread indefinitely. Writesonic doesn't document its rate limits.
MAX_RETRY_AFTER_SECONDS = 120


class WritesonicRetryableError(Exception):
    def __init__(self, message: str, retry_after: Optional[float] = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Parse a `Retry-After` header (delta-seconds or HTTP-date) into seconds-from-now.

    Returns None for a missing, malformed, or already-elapsed value so the caller falls back to
    its default backoff."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        seconds = float(value)
        return seconds if seconds >= 0 else None
    except ValueError:
        pass
    try:
        retry_dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if retry_dt.tzinfo is None:
        retry_dt = retry_dt.replace(tzinfo=UTC)
    delta = (retry_dt - datetime.now(UTC)).total_seconds()
    return delta if delta > 0 else None


_EXPONENTIAL_JITTER = wait_exponential_jitter(initial=2, max=60)


def _retry_wait(retry_state: RetryCallState) -> float:
    """Prefer the server's `Retry-After` cool-down on a 429/5xx; otherwise back off exponentially."""
    outcome = retry_state.outcome
    exc = outcome.exception() if outcome is not None else None
    if isinstance(exc, WritesonicRetryableError) and exc.retry_after is not None:
        return min(exc.retry_after, MAX_RETRY_AFTER_SECONDS)
    return _EXPONENTIAL_JITTER(retry_state)


@dataclasses.dataclass(frozen=False)
class WritesonicResumeConfig:
    # Daily endpoints resume at (day, page); config endpoints only use `page`. Fan-out endpoints
    # resume at (pages listing page, last finished parent on it).
    date: Optional[str] = None
    page: Optional[int] = None
    parent_id: Optional[str] = None


def _to_date(value: Any) -> Optional[date]:
    """Coerce a stored incremental cursor (date, datetime, epoch seconds, or ISO string) to a date."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return (value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)).date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC).date()
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def _base_params(site_url: str, project_id: Optional[str]) -> dict[str, Any]:
    params: dict[str, Any] = {"url": site_url}
    if project_id:
        params["project_id"] = project_id
    return params


def validate_credentials(
    api_key: str,
    site_url: str,
    project_id: Optional[str] = None,
    schema_name: Optional[str] = None,
) -> tuple[bool, str | None]:
    """Cheap probe against the websites config export to confirm the key and site URL work.

    Every GEO export endpoint sits behind the same API key scope, so one probe covers all
    schemas — a per-schema check (`schema_name` set) behaves identically."""
    url = urljoin(BASE_URL, "/v2/geo/presence/business/export/config/websites")
    try:
        response = _make_session(api_key).get(
            url,
            params={**_base_params(site_url, project_id), "size": 1},
            headers={"X-API-Key": api_key, "Accept": "application/json"},
            timeout=30,
        )
    except Exception:
        return False, "Could not reach Writesonic. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Writesonic rejected the API key. Check the key in your Writesonic API dashboard."
    if response.status_code == 403:
        return False, (
            "Your Writesonic plan does not include API access to GEO data. "
            "Upgrade to a plan with API access and try again."
        )
    if response.status_code == 404:
        return False, (
            "Writesonic could not find a tracked site for this URL. "
            "Check the site URL (and project ID, if set) against your Writesonic workspace."
        )
    if response.status_code == 422:
        return (
            False,
            "Writesonic rejected the site URL. Enter the full URL of the tracked site, e.g. https://example.com.",
        )
    return False, f"Writesonic returned an unexpected status ({response.status_code}) while validating credentials."


def _make_session(api_key: str) -> requests.Session:
    """Tracked session with the credential hardening the fixed-host connectors use.

    `redact_values` masks the API key in logged URLs and captured request samples (the
    `X-API-Key` header name isn't on the transport's denylist), and `allow_redirects=False`
    stops a 30x from replaying the credentialed header off-host."""
    return make_tracked_session(retry=NO_URLLIB_RETRY, redact_values=(api_key,), allow_redirects=False)


def _check_response(response: requests.Response, url: str, logger: FilteringBoundLogger) -> requests.Response:
    """Classify a Writesonic response: 429/5xx are retryable, other 4xx are terminal."""
    if response.status_code == 429 or response.status_code >= 500:
        headers = getattr(response, "headers", None) or {}
        retry_after = _parse_retry_after(headers.get("Retry-After"))
        raise WritesonicRetryableError(
            f"Writesonic API error (retryable): status={response.status_code}, url={url}",
            retry_after=retry_after,
        )

    if not response.ok:
        logger.error(f"Writesonic API error: status={response.status_code}, body={response.text[:500]}, url={url}")
        response.raise_for_status()

    return response


@retry_with_deadline(
    retry=retry_if_exception_type((WritesonicRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=_retry_wait,
    reraise=True,
)
def _get(
    path: str,
    *,
    api_key: str,
    logger: FilteringBoundLogger,
    params: Optional[dict[str, Any]] = None,
) -> requests.Response:
    url = urljoin(BASE_URL, path)
    response = _make_session(api_key).get(
        url,
        params=params,
        headers={"X-API-Key": api_key, "Accept": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    return _check_response(response, url, logger)


def _iter_pages(
    path: str,
    *,
    api_key: str,
    params: dict[str, Any],
    start_page: int,
    logger: FilteringBoundLogger,
) -> Iterator[tuple[int, list[dict[str, Any]]]]:
    """Walk page-number pagination for one request shape, yielding (page, items) per page."""
    page = start_page
    while True:
        response = _get(
            path,
            api_key=api_key,
            logger=logger,
            params={**params, "page": page, "size": PAGE_SIZE},
        )
        data = response.json()
        items = data.get("items") or []
        if not items:
            break

        yield page, items

        # The content-optimize exports name the page count `pages`.
        total_pages = data.get("total_pages", data.get("pages"))
        if total_pages is not None and page >= total_pages:
            break
        page += 1


def _iter_daily(
    endpoint_config: WritesonicEndpointConfig,
    *,
    api_key: str,
    site_url: str,
    project_id: Optional[str],
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[WritesonicResumeConfig],
    start_date: date,
    end_date: date,
) -> Iterator[list[dict[str, Any]]]:
    """Sync a daily export endpoint one UTC day at a time.

    The required `date` param is both the incremental granularity and the resume granularity.
    The next page is staged before each page's rows are yielded, so the pipeline commits it
    together with those rows."""
    resume = manager.load_state() if manager.can_resume() else None
    resumed_date = _to_date(resume.date) if resume and resume.date else None
    current = resumed_date or start_date
    start_page = resume.page if resume and resumed_date and resume.page else 1
    if resumed_date:
        logger.debug(f"Writesonic {endpoint_config.name}: resuming from {resumed_date.isoformat()} page {start_page}")

    while current <= end_date:
        day = current.isoformat()
        params = {**_base_params(site_url, project_id), "date": day}
        for page, items in _iter_pages(
            endpoint_config.path, api_key=api_key, params=params, start_page=start_page, logger=logger
        ):
            if endpoint_config.inject_date:
                # Content export rows don't carry the export date; stamp it in since it's part
                # of the primary key, the partition key, and the incremental cursor.
                items = [{**item, "date": day} for item in items]
            manager.save_state(WritesonicResumeConfig(date=day, page=page + 1))
            yield items

        next_day = current + timedelta(days=1)
        manager.save_state(WritesonicResumeConfig(date=next_day.isoformat(), page=1))
        # Every row of the day is yielded, so the staged day loses nothing.
        manager.safe_point()
        current = next_day
        start_page = 1


def _iter_config(
    endpoint_config: WritesonicEndpointConfig,
    *,
    api_key: str,
    site_url: str,
    project_id: Optional[str],
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[WritesonicResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Full refresh of a config export endpoint with page resume."""
    resume = manager.load_state() if manager.can_resume() else None
    start_page = resume.page if resume and resume.page else 1
    if resume and resume.page:
        logger.debug(f"Writesonic {endpoint_config.name}: resuming from page {start_page}")

    params = _base_params(site_url, project_id)
    for page, items in _iter_pages(
        endpoint_config.path, api_key=api_key, params=params, start_page=start_page, logger=logger
    ):
        manager.save_state(WritesonicResumeConfig(page=page + 1))
        yield items


def _iter_single(
    endpoint_config: WritesonicEndpointConfig,
    *,
    api_key: str,
    site_url: str,
    project_id: Optional[str],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """One unpaginated request. Top-level scalars (e.g. `last_scan_date`) are copied onto each row."""
    response = _get(endpoint_config.path, api_key=api_key, logger=logger, params=_base_params(site_url, project_id))
    data = response.json()
    items = data.get(endpoint_config.data_selector) or []
    extras = {
        key: value
        for key, value in data.items()
        if key != endpoint_config.data_selector and not isinstance(value, (list, dict))
    }
    if items:
        yield [{**item, **extras} for item in items]


def _select_issues(data: dict[str, Any]) -> list[dict[str, Any]]:
    return data.get("issues") or []


def _select_fixes(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"issue_type": group.get("issue_type"), **fix}
        for group in data.get("recommendations") or []
        for fix in group.get("fixes") or []
    ]


_FANOUT_ROW_SELECTORS: dict[str, Callable[[dict[str, Any]], list[dict[str, Any]]]] = {
    "content_optimize_issues": _select_issues,
    "content_optimize_recommendations": _select_fixes,
}


def _iter_page_fanout(
    endpoint_config: WritesonicEndpointConfig,
    *,
    api_key: str,
    site_url: str,
    project_id: Optional[str],
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[WritesonicResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Full refresh of a per-page content-optimize export, fanned out over the pages listing.

    Each child row gets its parent's `optimization_page_id` and `page_url`, since the issue and
    fix objects don't carry them."""
    select_rows = _FANOUT_ROW_SELECTORS[endpoint_config.name]
    resume = manager.load_state() if manager.can_resume() else None
    start_page = resume.page if resume and resume.page else 1
    resume_after = resume.parent_id if resume and resume.page else None
    if resume and resume.page:
        logger.debug(f"Writesonic {endpoint_config.name}: resuming from page {start_page} after {resume_after}")

    params = _base_params(site_url, project_id)
    for page, parents in _iter_pages(
        CONTENT_OPTIMIZE_PAGES_PATH, api_key=api_key, params=params, start_page=start_page, logger=logger
    ):
        if page == start_page and resume_after is not None:
            parent_ids = [parent.get("optimization_page_id") for parent in parents]
            # By id, not position: a parent removed since the interrupted run must not shift one out.
            if resume_after in parent_ids:
                parents = parents[parent_ids.index(resume_after) + 1 :]

        for parent in parents:
            rows: list[dict[str, Any]] = []
            page_url = parent.get("source_url")
            if page_url:
                try:
                    response = _get(
                        endpoint_config.path, api_key=api_key, logger=logger, params={**params, "page_url": page_url}
                    )
                except requests.HTTPError as e:
                    # A page removed between the listing and this request.
                    if e.response is None or e.response.status_code != 404:
                        raise
                else:
                    context = {"optimization_page_id": parent.get("optimization_page_id"), "page_url": page_url}
                    rows = [{**row, **context} for row in select_rows(response.json())]

            manager.save_state(WritesonicResumeConfig(page=page, parent_id=parent.get("optimization_page_id")))
            if rows:
                yield rows
            else:
                manager.safe_point()


def get_rows(
    api_key: str,
    site_url: str,
    project_id: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[WritesonicResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    endpoint_config = WRITESONIC_ENDPOINTS.get(endpoint)
    if endpoint_config is None:
        raise ValueError(f"Unknown Writesonic endpoint: {endpoint}")

    if endpoint_config.page_fanout:
        yield from _iter_page_fanout(
            endpoint_config,
            api_key=api_key,
            site_url=site_url,
            project_id=project_id,
            logger=logger,
            manager=manager,
        )
        return

    if endpoint_config.single_request:
        yield from _iter_single(
            endpoint_config, api_key=api_key, site_url=site_url, project_id=project_id, logger=logger
        )
        return

    if not endpoint_config.daily:
        yield from _iter_config(
            endpoint_config,
            api_key=api_key,
            site_url=site_url,
            project_id=project_id,
            logger=logger,
            manager=manager,
        )
        return

    last_value_date = _to_date(db_incremental_field_last_value) if should_use_incremental_field else None
    end_date = datetime.now(UTC).date()
    # Restart inclusively from the watermark day: its previous sync may have run mid-day and
    # captured partial data. Merge dedupes the re-fetched rows on the primary key.
    start_date = last_value_date or (end_date - timedelta(days=DEFAULT_LOOKBACK_DAYS))
    if start_date > end_date:
        # A future cursor (clock skew or bad data) would make the day loop a no-op and silently
        # skip the sync. Clamp to today so we still sync the latest day.
        logger.warning(
            f"Writesonic {endpoint}: incremental cursor {start_date.isoformat()} is in the future; syncing today"
        )
        start_date = end_date

    yield from _iter_daily(
        endpoint_config,
        api_key=api_key,
        site_url=site_url,
        project_id=project_id,
        logger=logger,
        manager=manager,
        start_date=start_date,
        end_date=end_date,
    )


def writesonic_source(
    api_key: str,
    site_url: str,
    project_id: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[WritesonicResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = WRITESONIC_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            site_url=site_url,
            project_id=project_id,
            endpoint=endpoint,
            logger=logger,
            manager=manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        sort_mode="asc",
    )
