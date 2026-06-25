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
from products.warehouse_sources.backend.temporal.data_imports.sources.teamwork.settings import (
    TEAMWORK_ENDPOINTS,
    TeamworkEndpointConfig,
)

# Max page size accepted by the majority of V3 endpoints.
PAGE_SIZE = 500
# A single V3 request is hard-capped at 50,000 records (= 100 pages of 500). We stop one run at that
# boundary rather than letting the API error out. Incremental endpoints resume past it on the next
# scheduled run (the cursor watermark has advanced); full-refresh endpoints can't, so we warn loudly.
MAX_PAGES = 100


class TeamworkRetryableError(Exception):
    pass


@dataclasses.dataclass
class TeamworkResumeConfig:
    # Next 1-based page number to fetch within the current sync window.
    page: int = 1
    # The `updatedAfter` cursor used for this sync's window, so a resumed run rebuilds the same query.
    updated_after: str | None = None


def normalize_host(site: str) -> str:
    """Turn a user-entered Teamwork site into a bare hostname.

    Accepts a subdomain (``mycompany``), a full host (``mycompany.teamwork.com``), or a pasted URL
    (``https://mycompany.teamwork.com/``). A value with no dot is treated as a subdomain of
    ``teamwork.com``. Region/custom hosts (``mycompany.eu.teamwork.com``) are preserved as-is.
    """
    host = site.strip()
    host = host.removeprefix("https://").removeprefix("http://")
    host = host.split("/", 1)[0].strip().rstrip(".").lower()
    if "." not in host:
        host = f"{host}.teamwork.com"
    return host


def base_url(host: str) -> str:
    return f"https://{host}/projects/api/v3"


def _auth_header(api_key: str) -> dict[str, str]:
    # Teamwork uses HTTP Basic auth with the API key as the username and any value as the password.
    token = base64.b64encode(f"{api_key}:x".encode()).decode()
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def _format_updated_after(value: Any) -> str:
    """Format a cursor value as the ``yyyy-mm-ddThh:mm:ssZ`` string the V3 ``updatedAfter`` param wants."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _build_params(config: TeamworkEndpointConfig, page: int, updated_after: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {"page": page, "pageSize": PAGE_SIZE}
    if config.order_by:
        params["orderBy"] = config.order_by
        params["orderMode"] = "asc"
    if updated_after:
        params["updatedAfter"] = updated_after
    return params


@retry(
    retry=retry_if_exception_type((TeamworkRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=60)

    # The session never follows redirects (see `get_rows`), so a 3xx means the validated host tried to
    # bounce us elsewhere. Refuse it rather than forwarding the Basic auth header off the host boundary.
    if 300 <= response.status_code < 400:
        raise ValueError(
            f"Teamwork API returned an unexpected redirect (status={response.status_code}, url={url}); "
            "refusing to forward credentials off the validated host."
        )

    # 429s resume after ~60s on Teamwork; let the exponential backoff handle it. 5xx are transient.
    if response.status_code == 429 or response.status_code >= 500:
        raise TeamworkRetryableError(f"Teamwork API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error("Teamwork API error", status=response.status_code, body=response.text, url=url)
        response.raise_for_status()

    return response.json()


def validate_credentials(host: str, api_key: str) -> bool:
    # /me.json is the cheapest authenticated probe — it only needs a valid key, no extra scopes.
    url = f"{base_url(host)}/me.json"
    try:
        # `allow_redirects=False`: a redirect would forward the Basic auth header off the validated host.
        response = make_tracked_session(allow_redirects=False).get(url, headers=_auth_header(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    host: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TeamworkResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = TEAMWORK_ENDPOINTS[endpoint]
    headers = _auth_header(api_key)
    # `allow_redirects=False`: a redirect would forward the Basic auth header off the validated host.
    session = make_tracked_session(allow_redirects=False)

    is_incremental = should_use_incremental_field and config.incremental_field is not None

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        page = resume.page
        updated_after = resume.updated_after
    else:
        page = 1
        updated_after = (
            _format_updated_after(db_incremental_field_last_value)
            if is_incremental and db_incremental_field_last_value
            else None
        )

    endpoint_url = f"{base_url(host)}{config.path}"

    while True:
        url = f"{endpoint_url}?{urlencode(_build_params(config, page, updated_after))}"
        data = _fetch_page(session, url, headers, logger)

        items = data.get(config.data_key, [])
        has_more = bool(data.get("meta", {}).get("page", {}).get("hasMore", False))

        if items:
            # Yield the page as-is; the pipeline buffers and batches. Save state AFTER yielding and
            # pointing at the page we just emitted, so a crash re-yields it (merge dedupes on the
            # primary key) rather than skipping it.
            yield items
            resumable_source_manager.save_state(TeamworkResumeConfig(page=page, updated_after=updated_after))

        if not items or not has_more:
            break

        if page >= MAX_PAGES:
            if is_incremental:
                logger.info(
                    f"Teamwork: reached the {MAX_PAGES * PAGE_SIZE}-record per-sync cap for '{endpoint}'; "
                    "remaining rows will sync on the next run as the incremental cursor advances."
                )
            else:
                logger.warning(
                    f"Teamwork: reached the {MAX_PAGES * PAGE_SIZE}-record per-sync cap for full-refresh "
                    f"endpoint '{endpoint}'; rows beyond this limit were not synced this run."
                )
            break

        page += 1


def teamwork_source(
    host: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TeamworkResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = TEAMWORK_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            host=host,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # Rows are requested ascending (orderMode=asc), so the pipeline can checkpoint the watermark
        # after every batch and resume safely mid-sync.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
