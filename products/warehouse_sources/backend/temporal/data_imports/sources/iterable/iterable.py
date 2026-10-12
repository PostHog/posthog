import io
import csv
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse

import orjson
import requests
from requests import Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.transport import BoundedRetry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BaseNextUrlPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.iterable.settings import (
    CAMPAIGN_METRICS,
    DEFAULT_EXPORT_LOOKBACK_DAYS,
    FAN_OUT_PRIMARY_KEYS,
    ITERABLE_ENDPOINTS,
    ITERABLE_EXPORT_ENDPOINTS,
    LIST_USERS,
    IterableExportEndpointConfig,
)

# Iterable is region-locked: a key issued in one data center only works against that data center.
ITERABLE_BASE_URLS: dict[str, str] = {
    "us": "https://api.iterable.com",
    "eu": "https://api.eu.iterable.com",
}

# Safety bound on the pagination loop. Iterable's list endpoints normally return everything in a
# single response, but if one ever starts returning `nextPageUrl` we don't want an unbounded scan.
MAX_PAGES = 10_000

CHUNK_SIZE = 5000
REQUEST_TIMEOUT = 300
EXPORT_WINDOW = timedelta(days=30)
# The Export API allows about 4 requests a minute per project.
EXPORT_REQUEST_INTERVAL_SECONDS = 15
CAMPAIGN_METRICS_BATCH_SIZE = 100

# The export and metrics endpoints have per-minute rate limits, so a 429 needs a much longer
# backoff than the default transport retry gives.
RATE_LIMITED_RETRY = BoundedRetry(
    total=5,
    backoff_factor=30,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET"]),
    raise_on_status=False,
)


@frozen
class IterableResumeConfig:
    next_url: str | None = None
    # ISO start of the next export window to fetch.
    export_window_start: str | None = None


def base_url_for_region(region: str | None) -> str:
    return ITERABLE_BASE_URLS.get((region or "us").lower(), ITERABLE_BASE_URLS["us"])


def _api_key_headers(api_key: str) -> dict[str, str]:
    # The Api-Key credential rides in a header the tracked session's name-based scrubber doesn't
    # know, so sessions using it mask it by value via `redact_values`.
    return {"Api-Key": api_key, "Accept": "application/json"}


def validate_credentials(api_key: str, region: str | None) -> bool:
    # `/api/channels` is a cheap, low-cardinality endpoint that requires a valid server-side key.
    url = f"{base_url_for_region(region)}/api/channels"
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        headers=_api_key_headers(api_key),
    )
    return ok


def _is_same_origin(base_url: str, url: str) -> bool:
    base = urlparse(base_url)
    target = urlparse(url)
    return (target.scheme, target.netloc) == (base.scheme, base.netloc)


def _resolve_next_url(base_url: str, next_page: Any) -> str | None:
    """Normalize the `nextPageUrl` value from a response body into an absolute URL.

    Absolute URLs are only followed when they point at the selected Iterable base URL.
    The session carries the `Api-Key` header, so a `nextPageUrl` aimed at another host
    (e.g. an attacker-controlled value echoed back in a response) would leak the key —
    such off-host pages stop pagination instead.
    """
    if not next_page or not isinstance(next_page, str):
        return None
    if next_page.startswith("http://") or next_page.startswith("https://"):
        return next_page if _is_same_origin(base_url, next_page) else None
    return f"{base_url}{next_page}" if next_page.startswith("/") else f"{base_url}/{next_page}"


class IterableNextPagePaginator(BaseNextUrlPaginator):
    """Follows Iterable's body-level ``nextPageUrl``.

    Iterable list endpoints normally return their whole result set in one response, but if one ever
    starts paging we resolve a relative ``nextPageUrl`` against the region base URL and refuse to
    follow an off-host absolute link. The session carries the ``Api-Key`` header, so an
    attacker-echoed off-host ``nextPageUrl`` would otherwise leak the key — such links stop
    pagination (the clean completion the hand-rolled source produced) rather than being followed.
    ``max_pages`` bounds the loop so a self-referential ``nextPageUrl`` can't scan unbounded.
    """

    def __init__(self, base_url: str, max_pages: int = MAX_PAGES) -> None:
        super().__init__()
        self.base_url = base_url
        self.max_pages = max_pages
        self._pages = 0

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        self._pages += 1
        try:
            next_page = response.json().get("nextPageUrl")
        except Exception:
            next_page = None
        next_url = _resolve_next_url(self.base_url, next_page)
        if next_url is not None and self._pages < self.max_pages:
            self._next_url = next_url
            self._has_next_page = True
        else:
            self._has_next_page = False


def _parse_iterable_datetime(value: Any) -> Any:
    """Parse an export timestamp such as ``2024-01-31 18:04:05 +00:00`` into an aware datetime.

    Anything that does not parse is returned unchanged.
    """
    if not isinstance(value, str):
        return value
    try:
        parsed = datetime.fromisoformat(value.strip().replace(" +", "+").replace(" -", "-"))
    except ValueError:
        return value
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _to_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, str) and value.strip():
        parsed = _parse_iterable_datetime(value.replace("Z", "+00:00"))
        return parsed if isinstance(parsed, datetime) else None
    return None


def _format_export_datetime(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S +00:00")


@frozen
class ExportWindow:
    start: datetime
    end: datetime


def _export_windows(start: datetime, end: datetime) -> Iterator[ExportWindow]:
    window_start = start
    while window_start < end:
        window_end = min(window_start + EXPORT_WINDOW, end)
        yield ExportWindow(start=window_start, end=window_end)
        window_start = window_end


def _stream_export_window(
    session: requests.Session,
    base_url: str,
    config: IterableExportEndpointConfig,
    window: ExportWindow,
) -> Iterator[list[dict[str, Any]]]:
    params = {
        "dataTypeName": config.data_type_name,
        "startDateTime": _format_export_datetime(window.start),
        "endDateTime": _format_export_datetime(window.end),
    }
    with session.get(
        f"{base_url}/api/export/data.json", params=params, timeout=REQUEST_TIMEOUT, stream=True
    ) as response:
        response.raise_for_status()
        batch: list[dict[str, Any]] = []
        for line in response.iter_lines():
            if not line:
                continue
            row = orjson.loads(line)
            if config.cursor_field in row:
                row[config.cursor_field] = _parse_iterable_datetime(row[config.cursor_field])
            batch.append(row)
            if len(batch) >= CHUNK_SIZE:
                yield batch
                batch = []
        if batch:
            yield batch


def _iter_export(
    session: requests.Session,
    base_url: str,
    config: IterableExportEndpointConfig,
    manager: ResumableSourceManager[IterableResumeConfig],
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    end = datetime.now(UTC)
    start = _to_datetime(db_incremental_field_last_value) or end - timedelta(days=DEFAULT_EXPORT_LOOKBACK_DAYS)
    if manager.can_resume():
        resume = manager.load_state()
        resume_start = _to_datetime(resume.export_window_start) if resume else None
        if resume_start is not None:
            start = resume_start

    for index, window in enumerate(_export_windows(start, end)):
        if index > 0:
            time.sleep(EXPORT_REQUEST_INTERVAL_SECONDS)
        # Hold back one batch so the next window's cursor is staged before the window's last
        # batch is yielded: the pipeline then commits it only once the whole window is written.
        pending: list[dict[str, Any]] | None = None
        for batch in _stream_export_window(session, base_url, config, window):
            if pending is not None:
                yield pending
            pending = batch
        if window.end < end:
            manager.save_state(IterableResumeConfig(export_window_start=window.end.isoformat()))
        if pending is not None:
            yield pending
        else:
            manager.safe_point()


def _get_ids(session: requests.Session, base_url: str, path: str, data_key: str) -> list[Any]:
    response = session.get(f"{base_url}{path}", timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return [item["id"] for item in response.json().get(data_key, []) if item.get("id") is not None]


def _iter_list_users(session: requests.Session, base_url: str) -> Iterator[list[dict[str, Any]]]:
    for list_id in _get_ids(session, base_url, "/api/lists", "lists"):
        with session.get(
            f"{base_url}/api/lists/getUsers", params={"listId": list_id}, timeout=REQUEST_TIMEOUT, stream=True
        ) as response:
            response.raise_for_status()
            batch: list[dict[str, Any]] = []
            # One identifier per line: the email, or the userId for users without one.
            for line in response.iter_lines():
                user = line.decode("utf-8").strip()
                if not user:
                    continue
                batch.append({"listId": list_id, "email": user})
                if len(batch) >= CHUNK_SIZE:
                    yield batch
                    batch = []
            if batch:
                yield batch


def _parse_campaign_metrics_csv(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in csv.DictReader(io.StringIO(text)):
        record: dict[str, Any] = {key: (value if value != "" else None) for key, value in row.items() if key}
        # Cast the id so it joins to the integer `campaigns.id`.
        campaign_id = record.get("id")
        if isinstance(campaign_id, str) and campaign_id.isdigit():
            record["id"] = int(campaign_id)
        rows.append(record)
    return rows


def _iter_campaign_metrics(session: requests.Session, base_url: str) -> Iterator[list[dict[str, Any]]]:
    campaign_ids = _get_ids(session, base_url, "/api/campaigns", "campaigns")
    for offset in range(0, len(campaign_ids), CAMPAIGN_METRICS_BATCH_SIZE):
        batch_ids = campaign_ids[offset : offset + CAMPAIGN_METRICS_BATCH_SIZE]
        response = session.get(
            f"{base_url}/api/campaigns/metrics",
            params=[("campaignId", campaign_id) for campaign_id in batch_ids],
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        rows = _parse_campaign_metrics_csv(response.text)
        if rows:
            yield rows


def _make_session(api_key: str) -> requests.Session:
    # `requests` only strips `Authorization` on a cross-host redirect, so a redirect would replay the
    # Api-Key header to the new host.
    return make_tracked_session(
        retry=RATE_LIMITED_RETRY,
        headers=_api_key_headers(api_key),
        redact_values=(api_key,),
        allow_redirects=False,
    )


def _export_source_response(
    api_key: str,
    base_url: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[IterableResumeConfig],
    db_incremental_field_last_value: Any,
) -> SourceResponse:
    config = ITERABLE_EXPORT_ENDPOINTS[endpoint]
    partition_key = config.cursor_field if config.partition_by_cursor else None
    return SourceResponse(
        name=endpoint,
        items=lambda: _iter_export(
            _make_session(api_key), base_url, config, resumable_source_manager, db_incremental_field_last_value
        ),
        primary_keys=None,
        partition_count=1 if partition_key else None,
        partition_size=1 if partition_key else None,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
        sort_mode="asc",
    )


def iterable_source(
    api_key: str,
    region: str | None,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[IterableResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    base_url = base_url_for_region(region)

    if endpoint in ITERABLE_EXPORT_ENDPOINTS:
        return _export_source_response(
            api_key, base_url, endpoint, resumable_source_manager, db_incremental_field_last_value
        )

    if endpoint == CAMPAIGN_METRICS:
        return SourceResponse(
            name=endpoint,
            items=lambda: _iter_campaign_metrics(_make_session(api_key), base_url),
            primary_keys=FAN_OUT_PRIMARY_KEYS[endpoint],
            supports_resume=False,
        )

    if endpoint == LIST_USERS:
        return SourceResponse(
            name=endpoint,
            items=lambda: _iter_list_users(_make_session(api_key), base_url),
            primary_keys=FAN_OUT_PRIMARY_KEYS[endpoint],
            supports_resume=False,
        )

    config = ITERABLE_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url,
            # Only the non-secret Accept header goes here; the Api-Key credential is supplied via the
            # framework auth config so its value is redacted from logs and sampled request captures.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "api_key", "api_key": api_key, "name": "Api-Key", "location": "header"},
            "paginator": IterableNextPagePaginator(base_url),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    # `.get(data_key, [])` in the hand-rolled source treated a missing key as zero
                    # rows, not an error — so the selector is NOT required (no fail-loud here).
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        # Only resume from a same-origin URL. A resume URL pointing off-host (corrupted/poisoned
        # state) must not be requested with the Api-Key header — start from the top instead.
        if resume is not None and resume.next_url and _is_same_origin(base_url, resume.next_url):
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(IterableResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
    )
