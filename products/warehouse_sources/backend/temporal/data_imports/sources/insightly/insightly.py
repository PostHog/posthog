import re
import base64
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
from products.warehouse_sources.backend.temporal.data_imports.sources.insightly.settings import (
    INSIGHTLY_ENDPOINTS,
    InsightlyEndpointConfig,
)

API_VERSION = "v3.1"
# Insightly caps list pages at 500 items (default is 100).
PAGE_SIZE = 500
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5

# A pod/instance is a short region token such as `na1`, `eu1`, `aps1`.
_POD_RE = re.compile(r"^[a-z0-9]+$")
_POD_FROM_URL_RE = re.compile(r"api\.([a-z0-9]+)\.insightly\.com")


class InsightlyRetryableError(Exception):
    pass


@dataclasses.dataclass
class InsightlyResumeConfig:
    # Offset (`skip`) of the next page to fetch. The `updated_after_utc` filter is rebuilt from the
    # job's incremental value at resume time, so it never needs to be persisted here.
    skip: int


def normalize_pod(raw: str) -> str:
    """Reduce whatever the user pasted to the bare Insightly pod token.

    Accepts ``na1`` or a full API URL (``https://api.na1.insightly.com/v3.1``). Raising on anything
    that isn't a plain pod token also pins outbound traffic to ``api.<pod>.insightly.com`` (no SSRF
    to arbitrary hosts).
    """
    pod = raw.strip().lower()
    match = _POD_FROM_URL_RE.search(pod)
    if match:
        pod = match.group(1)
    if not _POD_RE.match(pod):
        raise ValueError(f"Invalid Insightly pod/instance: {raw!r}")
    return pod


def base_url(pod: str) -> str:
    return f"https://api.{normalize_pod(pod)}.insightly.com/{API_VERSION}"


def _auth_headers(api_key: str) -> dict[str, str]:
    # Insightly uses HTTP Basic auth with the API key as the username and a blank password.
    token = base64.b64encode(f"{api_key}:".encode()).decode()
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def _format_updated_after(value: Any) -> str:
    """Format the incremental cursor as ISO 8601 with a trailing Z, which `updated_after_utc` expects
    (e.g. ``2018-04-09T16:58:14Z``)."""
    if isinstance(value, datetime):
        dt = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        # Already a string cursor (e.g. the raw DATE_UPDATED_UTC value round-tripped from the DB).
        return str(value)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_params(
    config: InsightlyEndpointConfig,
    skip: int,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"top": PAGE_SIZE, "skip": skip}
    if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value:
        params["updated_after_utc"] = _format_updated_after(db_incremental_field_last_value)
    return params


def _build_url(pod: str, path: str, params: dict[str, Any]) -> str:
    return f"{base_url(pod)}{path}?{urlencode(params)}"


def validate_credentials(pod: str, api_key: str, path: str = "/Contacts") -> Optional[int]:
    """Return the status code of a cheap authenticated probe, or ``None`` on transport error.

    Requests a single row from ``path`` so a genuine key returns 200, a bad key 401, and a key
    without scope for that resource 403. Built outside the ``try`` so an invalid-pod ``ValueError``
    propagates rather than being flattened to ``None`` by the transport-error handler.
    """
    url = _build_url(pod, path, {"top": 1})
    try:
        session = make_tracked_session(headers=_auth_headers(api_key), redact_values=(api_key,))
        response = session.get(url, timeout=10)
        return response.status_code
    except Exception:
        return None


def get_rows(
    pod: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InsightlyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = INSIGHTLY_ENDPOINTS[endpoint]
    # `redact_values` masks the key inside the base64 Authorization header in logged URLs / captured
    # samples, on top of the name-based denylist that already scrubs the header itself.
    session = make_tracked_session(headers=_auth_headers(api_key), redact_values=(api_key,))

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        skip = resume_config.skip
        logger.debug(f"Insightly: resuming {endpoint} from skip={skip}")
    else:
        skip = 0

    @retry(
        retry=retry_if_exception_type((InsightlyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> Any:
        response = session.get(page_url, timeout=REQUEST_TIMEOUT_SECONDS)

        # Insightly rate-limits at 10 req/s plus daily caps, returning 429; retry those and
        # transient 5xx with exponential backoff.
        if response.status_code == 429 or response.status_code >= 500:
            raise InsightlyRetryableError(
                f"Insightly API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"Insightly API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        url = _build_url(
            pod, config.path, _build_params(config, skip, should_use_incremental_field, db_incremental_field_last_value)
        )
        data = fetch_page(url)
        # Insightly list endpoints return a bare JSON array. Anything else (a 2xx error envelope,
        # an HTML gateway page) would otherwise make `items` empty and silently end the sync with
        # no rows and no error — so fail loudly instead of masking it as an empty table.
        if not isinstance(data, list):
            raise ValueError(f"Insightly API returned an unexpected {type(data).__name__} response for {url}")
        items = data

        if items:
            yield items

        # A short page (fewer than a full `top`) is the last page — offset pagination is done.
        if len(items) < PAGE_SIZE:
            break

        skip += PAGE_SIZE
        # Save the next offset only after the current page has been yielded, so a crash resumes at
        # this page rather than past it. Merge dedupes any rows re-yielded on resume by primary key.
        resumable_source_manager.save_state(InsightlyResumeConfig(skip=skip))


def insightly_source(
    pod: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InsightlyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = INSIGHTLY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            pod=pod,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        # Insightly paginates in record-id (creation) order, so rows for a given sync arrive roughly
        # oldest-first; DATE_UPDATED_UTC is not strictly monotonic across pages. We keep the same
        # `updated_after_utc` filter on every page (offset pagination reuses the query), so an
        # incremental sync never walks unbounded history — and if Insightly ever ignored the filter,
        # the sync degrades to full-refresh cost, never incorrect data (merge dedupes on the id).
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
