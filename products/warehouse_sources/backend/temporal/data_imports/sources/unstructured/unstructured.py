"""Transport for the Unstructured Platform API (https://docs.unstructured.io).

The Platform API is plain REST/JSON authenticated with a single `unstructured-api-key` header. Four
list endpoints are synced: `/api/v1/workflows/`, `/api/v1/jobs/`, `/api/v1/sources/`, and
`/api/v1/destinations/`. Each returns a bare JSON array of objects (no envelope). Only `/workflows/`
is paginated (page / page_size); the rest return their whole list in one response.

Two per-job tables fan out over `/api/v1/jobs/`: `/jobs/{id}/details` (one object per job) and
`/jobs/{id}/failed-files` (offset paging with `next_offset`). `/api/v1/notifications` is an event log
wrapped in `{"events": [...], "next_cursor": ...}`, ordered newest first with cursor paging.

Incremental sync is offered only for notifications, through the server-side `since` filter. Only
`/workflows/` also exposes a server-side timestamp filter (`created_since`), and there the resource is
mutable config (status / schedule / updated_at change over time), so filtering on `created_at` would
freeze already-synced rows and miss updates. The jobs / sources / destinations endpoints expose no
server-side time filter at all, so a "since" sync would re-page the full list anyway. These are all
low-volume inventory tables, so they ship as a full refresh, which reflects the correct current state
each sync. The filters and per-endpoint behavior were verified against the live Platform API OpenAPI
spec (versions 3.1.1 and 3.3.0); they were not smoke-tested against a real key, so a future implementer
enabling more incremental tables should confirm `created_since` actually filters before relying on it.
The workflows `sort_by=created_at` below is similarly taken from the spec (sort_by is a free-form string
defaulting to `id`) but unverified against a live key; if the API rejects it, drop the sort params and
fall back to the default `id` ordering.
"""

import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Optional
from urllib.parse import urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    make_tracked_session,
    retry_with_deadline,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.unstructured.settings import (
    UNSTRUCTURED_ENDPOINTS,
    UnstructuredEndpointConfig,
)

DEFAULT_BASE_URL = "https://platform.unstructuredapp.io"
# /workflows/ default page_size is 20; pull larger pages to cut round-trips on busy accounts.
WORKFLOWS_PAGE_SIZE = 100
# The largest page sizes the spec allows for these endpoints.
NOTIFICATIONS_PAGE_SIZE = 100
FAILED_FILES_PAGE_SIZE = 1000
JOBS_PATH = "/api/v1/jobs/"
REQUEST_TIMEOUT = 60
HOST_NOT_ALLOWED_ERROR = "This API host is not allowed"


class UnstructuredRetryableError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class UnstructuredResumeConfig:
    # 1-based index of the next /workflows/ page to fetch.
    next_page: int = 1
    # Cursor of the next /notifications page.
    next_cursor: str | None = None


def normalize_base_url(base_url: str | None) -> str:
    """Return the API origin as `https://<host>` with no trailing slash, defaulting to the platform host.

    Accounts can be provisioned with a custom API host, so the origin is user-configurable. The scheme
    is forced to https so a customer-entered `http://` host can't downgrade the key to plaintext.
    Endpoint paths already carry their own leading segment (`/api/v1/...`), so we only need the origin.
    """
    cleaned = (base_url or "").strip()
    if not cleaned:
        return DEFAULT_BASE_URL
    cleaned = re.sub(r"^https?://", "", cleaned, flags=re.IGNORECASE).rstrip("/")
    return f"https://{cleaned}" if cleaned else DEFAULT_BASE_URL


def _host_from_base_url(base_url: str | None) -> str:
    return (urlparse(normalize_base_url(base_url)).hostname or "").lower()


# Authority chars that let `urlparse` and the HTTP client disagree on where the host ends. A userinfo
# separator or a (raw or percent-encoded) backslash in `https://169.254.169.254\@example.com` makes
# `urlparse` report `example.com` while requests/urllib3 may connect to the internal IP — an SSRF
# bypass of the host check. No legitimate API origin carries these, so reject them outright.
_UNSAFE_URL_CHARS = re.compile(r"[\\@]|%5c|%40", re.IGNORECASE)


def _check_host(base_url: str | None, team_id: int) -> tuple[bool, str | None]:
    raw = (base_url or "").strip()
    if raw and _UNSAFE_URL_CHARS.search(raw):
        return False, HOST_NOT_ALLOWED_ERROR
    return _is_host_safe(_host_from_base_url(base_url), team_id)


def _headers(api_key: str) -> dict[str, str]:
    return {"unstructured-api-key": api_key, "Accept": "application/json"}


def _drop_sensitive_fields(rows: list[dict[str, Any]], drop_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    # Strip credential-bearing fields (e.g. the connector `config` object) before rows are persisted,
    # so secrets never land in a warehouse table readable by anyone with query access.
    if not drop_fields:
        return rows
    return [{k: v for k, v in row.items() if k not in drop_fields} for row in rows]


@retry_with_deadline(
    retry=retry_if_exception_type(
        (
            UnstructuredRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_json(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    params: Optional[dict[str, Any]],
    logger: FilteringBoundLogger,
    allow_not_found: bool = False,
) -> Any:
    response = session.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)

    # The session never follows redirects (SSRF hardening); surface a 30x as an error rather than
    # parsing the redirect body, so a customer-controlled host can't quietly point the sync elsewhere.
    if response.is_redirect or response.is_permanent_redirect:
        logger.error(f"Unstructured API returned an unexpected redirect: status={response.status_code}, url={url}")
        raise requests.HTTPError(
            f"Unexpected redirect from Unstructured API (status={response.status_code})", response=response
        )

    if response.status_code == 429 or response.status_code >= 500:
        raise UnstructuredRetryableError(
            f"Unstructured API error (retryable): status={response.status_code}, url={url}"
        )

    # A job deleted between the /jobs/ listing and its per-job request has nothing left to sync.
    if allow_not_found and response.status_code == 404:
        return None

    if not response.ok:
        logger.error(f"Unstructured API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _fetch(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    params: Optional[dict[str, Any]],
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    data = _fetch_json(session, url, headers, params, logger)
    # Every list endpoint returns a bare array; guard against an unexpected envelope so a shape change
    # surfaces as an empty sync rather than a crash deep in the pipeline.
    if not isinstance(data, list):
        logger.warning(f"Unstructured API returned a non-list body for {url}; got {type(data).__name__}")
        return []
    return data


def _format_since(value: Any) -> str:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()
    return str(value)


def _job_fields(job: dict[str, Any]) -> dict[str, Any]:
    return {"workflow_id": job.get("workflow_id"), "job_created_at": job.get("created_at")}


def _get_job_details(
    session: requests.Session,
    origin: str,
    config: UnstructuredEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    for job in _fetch(session, f"{origin}{JOBS_PATH}", headers, None, logger):
        job_id = job.get("id")
        if not job_id:
            continue
        url = f"{origin}{config.path.format(job_id=job_id)}"
        details = _fetch_json(session, url, headers, None, logger, allow_not_found=True)
        if isinstance(details, dict):
            yield [{**details, **_job_fields(job)}]


def _get_job_failed_files(
    session: requests.Session,
    origin: str,
    config: UnstructuredEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    for job in _fetch(session, f"{origin}{JOBS_PATH}", headers, None, logger):
        job_id = job.get("id")
        # The job listing already counts failures, so a job with none needs no request. A null count
        # (older data planes) is fetched anyway.
        if not job_id or job.get("failed_file_count") == 0:
            continue
        url = f"{origin}{config.path.format(job_id=job_id)}"
        offset = 0
        while True:
            # Without paging params the API returns only a legacy sample of the failures.
            params = {"limit": FAILED_FILES_PAGE_SIZE, "offset": offset}
            data = _fetch_json(session, url, headers, params, logger, allow_not_found=True)
            if not isinstance(data, dict):
                break

            rows = [
                {
                    **failed_file,
                    "job_id": job_id,
                    **_job_fields(job),
                    "node_id": (failed_file.get("node") or {}).get("id"),
                }
                for failed_file in data.get("failed_files") or []
                if isinstance(failed_file, dict)
            ]
            if rows:
                yield rows

            next_offset = data.get("next_offset")
            if not isinstance(next_offset, int) or next_offset <= offset:
                break
            offset = next_offset


def _get_notifications(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UnstructuredResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.next_cursor if resume else None

    base_params: dict[str, Any] = {"limit": NOTIFICATIONS_PAGE_SIZE}
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        base_params["since"] = _format_since(db_incremental_field_last_value)

    while True:
        params = {**base_params, "cursor": cursor} if cursor else base_params
        data = _fetch_json(session, url, headers, params, logger)
        if not isinstance(data, dict):
            logger.warning(f"Unstructured API returned a non-object body for {url}; got {type(data).__name__}")
            return

        events = [event for event in data.get("events") or [] if isinstance(event, dict)]
        next_cursor = data.get("next_cursor")
        if next_cursor:
            resumable_source_manager.save_state(UnstructuredResumeConfig(next_cursor=next_cursor))

        if events:
            yield events
        elif next_cursor:
            resumable_source_manager.safe_point()

        if not next_cursor or next_cursor == cursor:
            return
        cursor = next_cursor


def get_rows(
    base_url: str | None,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UnstructuredResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    # The API host is customer-controlled, so block hosts resolving to private/internal addresses
    # (SSRF) before sending the key. Only enforced on cloud — see `_is_host_safe`.
    host_ok, host_err = _check_host(base_url, team_id)
    if not host_ok:
        raise ValueError(host_err or HOST_NOT_ALLOWED_ERROR)

    config = UNSTRUCTURED_ENDPOINTS[endpoint]
    headers = _headers(api_key)
    origin = normalize_base_url(base_url)
    url = f"{origin}{config.path}"
    # One session reused across pages so urllib3 keeps the connection alive between requests.
    # `allow_redirects=False` keeps the credentialed request pinned to the validated host so a
    # customer-controlled host can't 30x the `unstructured-api-key` header off-origin (SSRF). The
    # key is also registered for value-based redaction so it never lands in a captured HTTP sample.
    # HTTP sample capture is disabled for endpoints with drop_fields (sources / destinations): the
    # adapter records the raw response body before `_drop_sensitive_fields` runs, so capturing it
    # would persist the connector `config` secrets into the sample bucket that stripping removes.
    session = make_tracked_session(
        redact_values=(api_key,), allow_redirects=False, capture=not bool(config.drop_fields)
    )

    if config.fan_out_jobs:
        fan_out = _get_job_details if endpoint == "job_details" else _get_job_failed_files
        yield from fan_out(session, origin, config, headers, logger)
        return

    if endpoint == "notifications":
        yield from _get_notifications(
            session,
            url,
            headers,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
        return

    if not config.paginated:
        rows = _drop_sensitive_fields(_fetch(session, url, headers, None, logger), config.drop_fields)
        if rows:
            yield rows
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume else 1
    if resume is not None:
        logger.debug(f"Unstructured: resuming {endpoint} from page {page}")

    while True:
        params = {
            "page": page,
            "page_size": WORKFLOWS_PAGE_SIZE,
            # Sort by the stable creation timestamp ascending so rows added mid-sync land on the last
            # page instead of shifting earlier rows across a page boundary (skip/duplicate risk).
            "sort_by": "created_at",
            "sort_direction": "asc",
        }
        rows = _fetch(session, url, headers, params, logger)
        if not rows:
            break

        yield _drop_sensitive_fields(rows, config.drop_fields)

        # A short page is the last page — the API has no explicit "has more" flag, so there is
        # nothing left to resume to and we skip the checkpoint.
        if len(rows) < WORKFLOWS_PAGE_SIZE:
            break

        # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last page
        # rather than skipping it; merge/replace dedupes the re-pulled rows on the primary key.
        page += 1
        resumable_source_manager.save_state(UnstructuredResumeConfig(next_page=page))


def unstructured_source(
    base_url: str | None,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[UnstructuredResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config: UnstructuredEndpointConfig = UNSTRUCTURED_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            base_url=base_url,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            team_id=team_id,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # The per-job walks keep no job or offset checkpoint, so a handoff would repeat every request.
        supports_resume=not config.fan_out_jobs,
    )


def validate_credentials(base_url: str | None, api_key: str, team_id: int) -> tuple[bool, str | None]:
    """Cheap probe: list a single workflow. 200 means the key is genuine (an empty account returns []).

    Only checks reachability + auth, not per-endpoint scope; the Platform API key is account-wide, so a
    valid key reaches every list endpoint. Blocks internal/private hosts (SSRF) before sending the key.
    """
    host_ok, host_err = _check_host(base_url, team_id)
    if not host_ok:
        return False, host_err or HOST_NOT_ALLOWED_ERROR

    url = f"{normalize_base_url(base_url)}/api/v1/workflows/"
    try:
        # `allow_redirects=False` stops a validated-but-hostile host from 30x-ing the probe (and the
        # `unstructured-api-key` header) to another origin; a redirect then fails the status check
        # below. The key is registered for value-based redaction so it never lands in a captured sample.
        response = make_tracked_session(redact_values=(api_key,), allow_redirects=False).get(
            url,
            headers=_headers(api_key),
            params={"page": 1, "page_size": 1},
            timeout=REQUEST_TIMEOUT,
        )
        return response.status_code == 200, None if response.status_code == 200 else "Invalid Unstructured API key"
    except Exception:
        return False, "Invalid Unstructured API key"
