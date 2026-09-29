from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit

import requests
from dateutil import parser as date_parser
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.fastly.settings import (
    FASTLY_ENDPOINTS,
    FastlyEndpointConfig,
)

FASTLY_BASE_URL = "https://api.fastly.com"

# Fastly caps read requests at ~6,000/minute per token. `/service` supports page-number pagination;
# the account's service count is small in practice, so a large page keeps the round-trip count down.
SERVICE_PAGE_SIZE = 100

# ACL entries and dictionary items page the same way, and both accept up to 100 records per page.
CHILD_PAGE_SIZE = 100

# `/billing/v3/invoices` caps `limit` at 200.
INVOICE_PAGE_LIMIT = 200

# The usage metrics API rejects a window longer than three months, so ask for the three ending now.
USAGE_METRICS_MONTHS = 3

# `/service-authorizations` is JSON:API and pages with `page[size]`, capped at 100.
SERVICE_AUTHORIZATION_PAGE_SIZE = 100

# Origin Inspector caps `limit` (timeseries per page) at 200.
ORIGIN_INSPECTOR_PAGE_LIMIT = 200

# Both metrics families are read in whole days. Day buckets close around 2am the following day, and
# a day is the coarsest bucket, so it keeps the row count proportionate to a warehouse table.
METRICS_DOWNSAMPLE = "day"

# Origin Inspector groups its timeseries by origin host, which is the breakdown the table is for.
ORIGIN_INSPECTOR_GROUP_BY = "host"

# Length in seconds of each bucket Fastly's metrics APIs report, by downsample name.
BUCKET_SECONDS: dict[str, int] = {"minute": 60, "hour": 60 * 60, "day": 24 * 60 * 60}

# A service without the Origin Inspector upgrade cannot serve its origin metrics. Fastly's docs do
# not pin down which status that is, so treat both refusals as "not enabled here" and move on rather
# than failing every other service's rows with it.
ORIGIN_INSPECTOR_UNAVAILABLE_STATUSES = frozenset({403, 404})


class FastlyRetryableError(Exception):
    pass


class FastlyPaginationError(Exception):
    pass


@frozen
class FastlyResumeConfig:
    # Next page URL for the paginated top-level `services` list.
    next_url: str | None = None
    # Bookmark for fan-out endpoints: the service we were processing when state was saved. On resume
    # we restart at this service and re-yield its rows (merge dedupes on the primary key).
    service_id: str | None = None
    # Opaque next-page cursor for the /billing/v3 endpoints, with the request it continues. A cursor
    # only continues the request that produced it, and the usage metrics window moves with the month.
    cursor: str | None = None
    cursor_request: str | None = None


@frozen
class _BucketTimeline:
    """The time grid an Origin Inspector page's `values` array is indexed against."""

    first_start_time: int
    bucket_seconds: int


def _get_headers(api_key: str) -> dict[str, str]:
    return {"Fastly-Key": api_key, "Accept": "application/json"}


def _build_url(base_url: str, params: dict[str, Any], safe: str = "") -> str:
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params, safe=safe)}"


@retry(
    retry=retry_if_exception_type(
        (
            FastlyRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> requests.Response:
    response = session.get(url, headers=headers, timeout=60)

    # 429 carries rate-limit reset headers; 5xx are transient. Both are retryable.
    if response.status_code == 429 or response.status_code >= 500:
        raise FastlyRetryableError(f"Fastly API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Fastly API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response


def _fetch_optional(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    ignore_statuses: frozenset[int],
) -> requests.Response | None:
    """Fetch a URL, returning None when the API refuses it with one of `ignore_statuses`."""
    try:
        return _fetch(session, url, headers, logger)
    except requests.HTTPError as error:
        status = error.response.status_code if error.response is not None else None
        if status in ignore_statuses:
            return None
        raise


def _require_fastly_host(url: str | None) -> str | None:
    """Reject a next-page URL that points anywhere but the Fastly API.

    Every request carries the customer's token in the `Fastly-Key` header, and a next-page link is
    read from a response rather than built here, so a link naming another host would send the token
    to that host. A resumed URL gets the same check, because it was a response link when it was
    stored."""
    if url is None:
        return None
    base = urlsplit(FASTLY_BASE_URL)
    target = urlsplit(url)
    if (target.scheme, target.netloc) != (base.scheme, base.netloc):
        raise FastlyPaginationError(f"Fastly returned a next page link outside the API host: {url}")
    return url


def _next_page_url(response: requests.Response) -> str | None:
    """Fastly signals the next page of `/service` via a standard `Link: <...>; rel="next"` header."""
    return _require_fastly_host(response.links.get("next", {}).get("url"))


def validate_credentials(api_key: str) -> bool:
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{FASTLY_BASE_URL}/current_user", headers=_get_headers(api_key), timeout=10
        )
        return response.status_code == 200
    except requests.RequestException:
        # A network blip / timeout at source-create can't confirm the token, so report it as invalid
        # rather than crashing setup. Non-request errors are unexpected and left to propagate.
        return False


def _ensure_id(row: dict[str, Any], field: str, value: str) -> dict[str, Any]:
    """Fastly's nested objects already carry their parent identifiers, but inject them defensively so
    a composite primary key is never missing a parent."""
    if not row.get(field):
        row = {**row, field: value}
    return row


def _ensure_service_id(row: dict[str, Any], service_id: str) -> dict[str, Any]:
    return _ensure_id(row, "service_id", service_id)


def _iter_linked_pages(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[requests.Response]:
    """Walk a Link-header paginated Fastly endpoint, yielding each page's response."""
    while True:
        response = _fetch(session, url, headers, logger)
        yield response
        next_url = _next_page_url(response)
        if not next_url:
            return
        # A next link that points at the page just read would loop forever and re-yield its rows.
        if next_url == url:
            raise FastlyPaginationError(f"Fastly returned an unchanged next page link for {url}")
        url = next_url


def _next_cursor(payload: dict[str, Any]) -> str | None:
    """Read the next-page cursor from a /billing/v3 response. Invoices carry `meta` at the top level
    while the usage metrics response nests it under `data`, so check both rather than assume one."""
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        data = payload.get("data")
        meta = data.get("meta") if isinstance(data, dict) else None
    if not isinstance(meta, dict):
        return None
    cursor = meta.get("next_cursor")
    return cursor if isinstance(cursor, str) and cursor else None


def _request_fingerprint(path: str, params: dict[str, Any]) -> str:
    return _build_url(path, dict(sorted(params.items())))


def _usage_metrics_window(today: datetime | None = None) -> dict[str, str]:
    """The `YYYY-MM` window covering the current month and the two before it."""
    now = today or datetime.now(tz=UTC)
    end_index = now.year * 12 + now.month - 1
    start_index = end_index - (USAGE_METRICS_MONTHS - 1)
    return {
        "start_month": f"{start_index // 12:04d}-{start_index % 12 + 1:02d}",
        "end_month": f"{end_index // 12:04d}-{end_index % 12 + 1:02d}",
    }


def _flatten_usage_metrics(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn a usage metrics page into one row per (usage type, service). Fastly's own spec models
    `data` as a single usage-type block; live responses may return a list of them, so accept both."""
    data = payload.get("data")
    blocks = data if isinstance(data, list) else [data] if isinstance(data, dict) else []

    rows: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        usage_type = {key: value for key, value in block.items() if key not in ("details", "meta")}
        for detail in block.get("details") or []:
            if isinstance(detail, dict):
                rows.append({**usage_type, **detail})
    return rows


def _as_epoch_seconds(value: Any) -> int | None:
    """Normalise a watermark into the Unix seconds the `from` / `start` params take."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return int(value.timestamp())
    if isinstance(value, int | float):
        return int(value)
    return None


def _flatten_json_api(item: dict[str, Any]) -> dict[str, Any]:
    """Lift a JSON:API resource's `attributes` into the row root and each `relationships` member down
    to a `<name>_id` column, so the row reads like every other Fastly table."""
    row = {key: value for key, value in item.items() if key not in ("attributes", "relationships")}

    attributes = item.get("attributes")
    if isinstance(attributes, dict):
        row.update(attributes)

    relationships = item.get("relationships")
    if isinstance(relationships, dict):
        for name, relationship in relationships.items():
            related = relationship.get("data") if isinstance(relationship, dict) else None
            if isinstance(related, dict):
                row[f"{name}_id"] = related.get("id")

    return row


def _next_body_link(payload: dict[str, Any]) -> str | None:
    """Read the next page from a JSON:API `links` object. Fastly returns a path there rather than an
    absolute URL, so resolve it against the API host."""
    links = payload.get("links")
    if not isinstance(links, dict):
        return None
    next_link = links.get("next")
    if not isinstance(next_link, str) or not next_link:
        return None
    return _require_fastly_host(urljoin(FASTLY_BASE_URL, next_link))


def _bucket_timeline(meta: dict[str, Any]) -> _BucketTimeline | None:
    """Resolve the bucket grid an Origin Inspector page reports against.

    The API returns one `values` entry per time bucket but puts no timestamp on the entry, so the
    bucket a value belongs to is its index counted forward from `meta.start`."""
    downsample = meta.get("downsample")
    bucket_seconds = BUCKET_SECONDS.get(downsample) if isinstance(downsample, str) else None
    start = meta.get("start")
    if bucket_seconds is None or not isinstance(start, str):
        return None

    try:
        parsed = date_parser.parse(start)
    except ValueError, OverflowError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return _BucketTimeline(first_start_time=int(parsed.timestamp()), bucket_seconds=bucket_seconds)


def _flatten_origin_inspector(payload: dict[str, Any], service_id: str) -> list[dict[str, Any]]:
    """Turn an Origin Inspector page into one row per (timeseries, time bucket)."""
    meta = payload.get("meta")
    timeline = _bucket_timeline(meta) if isinstance(meta, dict) else None
    if timeline is None:
        return []

    rows: list[dict[str, Any]] = []
    for entry in payload.get("data") or []:
        if not isinstance(entry, dict):
            continue
        dimensions = entry.get("dimensions")
        dimensions = dimensions if isinstance(dimensions, dict) else {}
        values = entry.get("values")
        if not isinstance(values, list):
            continue
        for index, value in enumerate(values):
            if not isinstance(value, dict):
                continue
            rows.append(
                {
                    **dimensions,
                    **value,
                    "service_id": service_id,
                    "start_time": timeline.first_start_time + index * timeline.bucket_seconds,
                }
            )
    return rows


def _iter_services(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[dict[str, Any]]:
    """Page through GET /service, yielding each service object. Used to drive fan-out endpoints."""
    url = _build_url(f"{FASTLY_BASE_URL}/service", {"per_page": SERVICE_PAGE_SIZE})
    while True:
        response = _fetch(session, url, headers, logger)
        items = response.json()
        if isinstance(items, list):
            yield from items
        next_url = _next_page_url(response)
        if not next_url:
            break
        url = next_url


def _active_version_number(
    session: requests.Session, service_id: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> int | None:
    """Resolve the version to read version-scoped resources from: the active version, else the highest
    version number. Fastly config resources are version-scoped, so syncing the active version reflects
    the service's current production configuration."""
    response = _fetch(session, f"{FASTLY_BASE_URL}/service/{service_id}/version", headers, logger)
    versions = response.json()
    if not isinstance(versions, list):
        return None

    active = [v["number"] for v in versions if isinstance(v, dict) and v.get("active") and "number" in v]
    if active:
        return max(active)

    numbers = [v["number"] for v in versions if isinstance(v, dict) and isinstance(v.get("number"), int)]
    return max(numbers) if numbers else None


def _get_object_rows(
    session: requests.Session, config: FastlyEndpointConfig, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    response = _fetch(session, f"{FASTLY_BASE_URL}{config.path}", headers, logger)
    data = response.json()
    if isinstance(data, dict):
        yield [data]
    elif isinstance(data, list) and data:
        yield data


def _get_plain_list_rows(
    session: requests.Session, config: FastlyEndpointConfig, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    response = _fetch(session, f"{FASTLY_BASE_URL}{config.path}", headers, logger)
    data = response.json()
    rows = [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []
    if rows:
        yield rows


def _get_json_api_rows(
    session: requests.Session,
    config: FastlyEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FastlyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        url = _require_fastly_host(resume.next_url) or ""
        logger.debug(f"Fastly: resuming {config.name} from URL: {url}")
    else:
        # Fastly documents its JSON:API pagination params with literal brackets, so send them
        # unencoded rather than as %5B / %5D.
        url = _build_url(f"{FASTLY_BASE_URL}{config.path}", {"page[size]": SERVICE_AUTHORIZATION_PAGE_SIZE}, safe="[]")

    while True:
        response = _fetch(session, url, headers, logger)
        payload = response.json()
        if not isinstance(payload, dict):
            return

        data = payload.get("data")
        rows = [_flatten_json_api(item) for item in data if isinstance(item, dict)] if isinstance(data, list) else []
        if rows:
            yield rows

        next_url = _next_body_link(payload)
        if not next_url:
            return
        if next_url == url:
            raise FastlyPaginationError(f"Fastly returned an unchanged next page link for {url}")
        # Saved AFTER yielding so a crash re-yields the last page rather than skipping it.
        resumable_source_manager.save_state(FastlyResumeConfig(next_url=next_url))
        url = next_url


def _get_stats_rows(
    session: requests.Session,
    config: FastlyEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    incremental_start: int | None,
) -> Iterator[list[dict[str, Any]]]:
    """Read `/stats`, which answers for every service in one unpaginated response keyed by service id.

    With no `from`, Fastly defaults the window to the last month, so a full refresh takes that and an
    incremental run takes everything since its watermark."""
    params: dict[str, Any] = {"by": METRICS_DOWNSAMPLE}
    if incremental_start is not None:
        params["from"] = incremental_start

    response = _fetch(session, _build_url(f"{FASTLY_BASE_URL}{config.path}", params), headers, logger)
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return

    for service_id, service_rows in data.items():
        if not isinstance(service_rows, list):
            continue
        rows = [_ensure_service_id(row, service_id) for row in service_rows if isinstance(row, dict)]
        if rows:
            yield rows


def _get_origin_inspector_rows(
    session: requests.Session,
    config: FastlyEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FastlyResumeConfig],
    incremental_start: int | None,
) -> Iterator[list[dict[str, Any]]]:
    params: dict[str, Any] = {
        "downsample": METRICS_DOWNSAMPLE,
        "group_by": ORIGIN_INSPECTOR_GROUP_BY,
        "limit": ORIGIN_INSPECTOR_PAGE_LIMIT,
    }
    if incremental_start is not None:
        params["start"] = incremental_start

    for service_id in _iter_services_from_bookmark(session, config, headers, logger, resumable_source_manager):
        url_base = f"{FASTLY_BASE_URL}{config.path.format(service_id=service_id)}"
        cursor: str | None = None

        while True:
            page_params = {**params, "cursor": cursor} if cursor else params
            response = _fetch_optional(
                session,
                _build_url(url_base, page_params),
                headers,
                logger,
                ORIGIN_INSPECTOR_UNAVAILABLE_STATUSES,
            )
            if response is None:
                logger.debug(f"Fastly: service {service_id} cannot serve origin metrics, skipping")
                break

            payload = response.json()
            if not isinstance(payload, dict):
                break

            rows = _flatten_origin_inspector(payload, service_id)
            if rows:
                yield rows

            next_cursor = _next_cursor(payload)
            if not next_cursor:
                break
            if next_cursor == cursor:
                raise FastlyPaginationError(f"Fastly returned an unchanged cursor for {url_base}")
            cursor = next_cursor


def _get_service_list_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FastlyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        url = _require_fastly_host(resume.next_url) or ""
        logger.debug(f"Fastly: resuming services from URL: {url}")
    else:
        url = _build_url(f"{FASTLY_BASE_URL}/service", {"per_page": SERVICE_PAGE_SIZE})

    while True:
        response = _fetch(session, url, headers, logger)
        items = response.json()
        if isinstance(items, list) and items:
            yield items

        next_url = _next_page_url(response)
        if not next_url:
            break
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it.
        resumable_source_manager.save_state(FastlyResumeConfig(next_url=next_url))
        url = next_url


def _iter_services_from_bookmark(
    session: requests.Session,
    config: FastlyEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FastlyResumeConfig],
) -> Iterator[str]:
    """Yield the service ids a fan-out endpoint still has to process, bookmarking each one once the
    caller has yielded its rows. If the bookmarked service no longer exists (deleted between runs),
    start over — merge dedupes the re-pulled rows."""
    services = list(_iter_services(session, headers, logger))
    service_ids = [s["id"] for s in services if isinstance(s, dict) and s.get("id")]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start = 0
    if resume is not None and resume.service_id and resume.service_id in service_ids:
        start = service_ids.index(resume.service_id)
        logger.debug(f"Fastly: resuming {config.name} from service_id={resume.service_id}")

    for service_id in service_ids[start:]:
        yield service_id
        # Bookmark the service AFTER yielding so a crash resumes here and re-yields. Advanced even for
        # a versionless (skipped) service so resume doesn't re-evaluate it every time.
        resumable_source_manager.save_state(FastlyResumeConfig(service_id=service_id))


def _get_version_scoped_rows(
    session: requests.Session,
    config: FastlyEndpointConfig,
    service_id: str,
    path: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    version = _active_version_number(session, service_id, headers, logger)
    if version is None:
        logger.debug(f"Fastly: service {service_id} has no versions, skipping {config.name}")
        return []

    response = _fetch(
        session, f"{FASTLY_BASE_URL}{path.format(service_id=service_id, version=version)}", headers, logger
    )
    data = response.json()
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def _get_fanout_rows(
    session: requests.Session,
    config: FastlyEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FastlyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    for service_id in _iter_services_from_bookmark(session, config, headers, logger, resumable_source_manager):
        if config.kind == "version_list":
            response = _fetch(session, f"{FASTLY_BASE_URL}/service/{service_id}/version", headers, logger)
            data = response.json()
            rows = [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []
        else:
            rows = _get_version_scoped_rows(session, config, service_id, config.path, headers, logger)

        rows = [_ensure_service_id(row, service_id) for row in rows]
        if rows:
            yield rows


def _get_version_resource_child_rows(
    session: requests.Session,
    config: FastlyEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FastlyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    parent_path = config.parent_path
    parent_key = config.parent_key
    assert parent_path is not None and parent_key is not None

    for service_id in _iter_services_from_bookmark(session, config, headers, logger, resumable_source_manager):
        parents = _get_version_scoped_rows(session, config, service_id, parent_path, headers, logger)

        for parent in parents:
            if config.skip_parent_flag and parent.get(config.skip_parent_flag):
                continue

            parent_id = parent.get("id")
            if not parent_id:
                continue

            path = config.path.format(service_id=service_id, parent_id=parent_id)
            url = _build_url(f"{FASTLY_BASE_URL}{path}", {"per_page": CHILD_PAGE_SIZE})
            for response in _iter_linked_pages(session, url, headers, logger):
                items = response.json()
                if not isinstance(items, list):
                    continue
                rows = [
                    _ensure_id(_ensure_service_id(row, service_id), parent_key, parent_id)
                    for row in items
                    if isinstance(row, dict)
                ]
                if rows:
                    yield rows


def _iter_billing_pages(
    session: requests.Session,
    path: str,
    params: dict[str, Any],
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FastlyResumeConfig],
) -> Iterator[dict[str, Any]]:
    request = _request_fingerprint(path, params)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    cursor = None
    if resume is not None and resume.cursor and resume.cursor_request == request:
        cursor = resume.cursor
        logger.debug(f"Fastly: resuming {path} from cursor")

    while True:
        page_params = {**params, "cursor": cursor} if cursor else params
        response = _fetch(session, _build_url(f"{FASTLY_BASE_URL}{path}", page_params), headers, logger)
        payload = response.json()
        if not isinstance(payload, dict):
            return

        yield payload

        next_cursor = _next_cursor(payload)
        if not next_cursor:
            return
        # A cursor that repeats the one just sent would loop forever and re-yield the same page.
        if next_cursor == cursor:
            raise FastlyPaginationError(f"Fastly returned an unchanged cursor for {path}")
        cursor = next_cursor
        # Saved AFTER yielding so a crash re-yields the last page rather than skipping it.
        resumable_source_manager.save_state(FastlyResumeConfig(cursor=cursor, cursor_request=request))


def _get_billing_list_rows(
    session: requests.Session,
    config: FastlyEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FastlyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    params = {"limit": INVOICE_PAGE_LIMIT}
    for payload in _iter_billing_pages(session, config.path, params, headers, logger, resumable_source_manager):
        data = payload.get("data")
        rows = [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []
        if rows:
            yield rows


def _get_billing_usage_metrics_rows(
    session: requests.Session,
    config: FastlyEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FastlyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    params = _usage_metrics_window()
    for payload in _iter_billing_pages(session, config.path, params, headers, logger, resumable_source_manager):
        rows = _flatten_usage_metrics(payload)
        if rows:
            yield rows


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FastlyResumeConfig],
    incremental_start: int | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = FASTLY_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # Redact the token so it never lands in captured HTTP samples — Fastly's custom `Fastly-Key`
    # header isn't covered by the transport's known-auth-header scrubbing.
    session = make_tracked_session(redact_values=(api_key,))

    if config.kind == "object":
        yield from _get_object_rows(session, config, headers, logger)
    elif config.kind == "plain_list":
        yield from _get_plain_list_rows(session, config, headers, logger)
    elif config.kind == "json_api_list":
        yield from _get_json_api_rows(session, config, headers, logger, resumable_source_manager)
    elif config.kind == "stats_list":
        yield from _get_stats_rows(session, config, headers, logger, incremental_start)
    elif config.kind == "origin_inspector":
        yield from _get_origin_inspector_rows(
            session, config, headers, logger, resumable_source_manager, incremental_start
        )
    elif config.kind == "service_list":
        yield from _get_service_list_rows(session, headers, logger, resumable_source_manager)
    elif config.kind == "version_resource_child":
        yield from _get_version_resource_child_rows(session, config, headers, logger, resumable_source_manager)
    elif config.kind == "billing_list":
        yield from _get_billing_list_rows(session, config, headers, logger, resumable_source_manager)
    elif config.kind == "billing_usage_metrics":
        yield from _get_billing_usage_metrics_rows(session, config, headers, logger, resumable_source_manager)
    else:
        yield from _get_fanout_rows(session, config, headers, logger, resumable_source_manager)


def fastly_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FastlyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = FASTLY_ENDPOINTS[endpoint]
    incremental_start = _as_epoch_seconds(db_incremental_field_last_value) if should_use_incremental_field else None

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            incremental_start=incremental_start,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # The metrics endpoints report buckets ascending within a service but walk the services one
        # after another, so the table as a whole arrives unordered.
        sort_mode=None if config.incremental_fields else "asc",
    )


__all__ = ["FastlyResumeConfig", "fastly_source", "validate_credentials"]
