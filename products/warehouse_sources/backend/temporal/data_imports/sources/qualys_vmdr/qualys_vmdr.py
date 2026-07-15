import json
import dataclasses
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlsplit, urlunsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.qualys_vmdr.settings import (
    QUALYS_VMDR_ENDPOINTS,
    QualysVmdrEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 300  # long list requests stream slowly with keep-alive bytes
MAX_RATE_LIMIT_WAIT_SECONDS = 120

# Qualys rejects any request without an X-Requested-With header.
_BASE_HEADERS = {"X-Requested-With": "PostHog Data Warehouse"}


class QualysVmdrRetryableError(Exception):
    def __init__(self, message: str, wait_seconds: int | None = None):
        super().__init__(message)
        self.wait_seconds = wait_seconds


@dataclasses.dataclass
class QualysVmdrResumeConfig:
    # Next truncated-batch URL (from the response's WARNING block), re-rooted onto the
    # configured API server. Carries the id_min cursor plus the original filter params.
    next_url: str


def build_base_url(api_server: str) -> str:
    """Normalize the user-supplied platform host into an https base URL.

    Users supply their account's regional API server (e.g. `qualysapi.qualys.eu`), with or
    without a scheme or trailing slash. The FO API is only served over TLS, so any scheme is
    forced to https.
    """
    api_server = api_server.strip().rstrip("/")
    if "://" in api_server:
        api_server = api_server.split("://", 1)[1]
    return f"https://{api_server}"


def _format_since_value(value: Any) -> str:
    """Format an incremental cursor as the `YYYY-MM-DDTHH:MM:SSZ` datetime Qualys expects."""
    if isinstance(value, datetime):
        utc_value = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


def _make_session(username: str, password: str) -> requests.Session:
    session = make_tracked_session(headers=_BASE_HEADERS, redact_values=(password,))
    session.auth = (username, password)
    return session


def _rate_limit_wait(retry_state: RetryCallState) -> float:
    """Honor the server-provided wait (X-RateLimit-ToWait-Sec) before falling back to backoff."""
    exception = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exception, QualysVmdrRetryableError) and exception.wait_seconds is not None:
        return float(min(exception.wait_seconds, MAX_RATE_LIMIT_WAIT_SECONDS))
    return wait_exponential_jitter(initial=1, max=30)(retry_state)


def _parse_xml(text: str) -> ET.Element:
    # Qualys streams keep-alive whitespace while generating long responses; strip it so the
    # XML declaration sits at the start of the document.
    return ET.fromstring(text.strip())


@retry(
    retry=retry_if_exception_type(
        (
            QualysVmdrRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=_rate_limit_wait,
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> ET.Element:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    # Qualys signals per-subscription rate/concurrency limits with 409 plus X-RateLimit /
    # X-Concurrency headers telling us how long to wait.
    if response.status_code in (409, 429) or response.status_code >= 500:
        wait_seconds: int | None = None
        for header in ("X-RateLimit-ToWait-Sec", "Retry-After"):
            raw_wait = response.headers.get(header)
            if raw_wait and raw_wait.isdigit():
                wait_seconds = int(raw_wait)
                break
        raise QualysVmdrRetryableError(
            f"Qualys API error (retryable): status={response.status_code}, url={response.url}",
            wait_seconds=wait_seconds,
        )

    if not response.ok:
        logger.error(f"Qualys API error: status={response.status_code}, body={response.text[:2000]}")
        response.raise_for_status()

    root = _parse_xml(response.text)

    # Parameter/permission errors come back as HTTP 200 with a SIMPLE_RETURN error document.
    if root.tag == "SIMPLE_RETURN":
        error_text = root.findtext(".//TEXT") or "unknown error"
        raise ValueError(f"Qualys API returned an error: {error_text}")

    return root


def _element_to_value(element: ET.Element) -> Any:
    """Recursively convert an XML element to text, or a dict/list structure for nested elements."""
    children = list(element)
    if not children:
        return element.text

    result: dict[str, Any] = {}
    for child in children:
        key = child.tag.lower()
        value = _element_to_value(child)
        if key in result:
            if not isinstance(result[key], list):
                result[key] = [result[key]]
            result[key].append(value)
        else:
            result[key] = value
    return result


def _element_to_row(element: ET.Element, skip_tags: set[str] | None = None) -> dict[str, Any]:
    """Convert one record element to a flat row dict.

    Scalar children become string columns. Nested children (CVE_LIST, DNS_DATA, TAGS, ...) are
    JSON-encoded: element repetition varies per record (one CVE vs many), so materializing them
    as native structs would produce conflicting Arrow types within a batch.
    """
    row: dict[str, Any] = {}
    for child in element:
        key = child.tag.lower()
        if skip_tags and child.tag in skip_tags:
            continue
        value = _element_to_value(child)
        row[key] = json.dumps(value) if isinstance(value, dict | list) else value
    return row


def _extract_rows(root: ET.Element, config: QualysVmdrEndpointConfig) -> Iterator[dict[str, Any]]:
    for item in root.iter(config.item_tag):
        if not config.flatten_host_detections:
            yield _element_to_row(item)
            continue

        # One row per (host, detection): host scalars prefixed host_* merged with the
        # detection's own fields. `unique_vuln_id` is the subscription-wide detection id.
        host_fields = {
            f"host_{key}": value for key, value in _element_to_row(item, skip_tags={"DETECTION_LIST"}).items()
        }
        for detection in item.iter("DETECTION"):
            yield {**host_fields, **_element_to_row(detection)}


def _next_batch_url(root: ET.Element, base_url: str) -> str | None:
    """Resolve the truncation WARNING's next-batch URL, re-rooted onto the configured server.

    When a response is truncated, Qualys returns a WARNING block whose URL carries the same
    params plus an advanced id_min. The URL is re-rooted onto the user-configured API server so
    credentials are only ever sent to the host the user supplied.
    """
    warning_url = root.findtext(".//WARNING/URL")
    if not warning_url:
        return None
    next_parts = urlsplit(warning_url.strip())
    base_parts = urlsplit(base_url)
    return urlunsplit((base_parts.scheme, base_parts.netloc, next_parts.path, next_parts.query, ""))


def _build_initial_url(
    base_url: str,
    config: QualysVmdrEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> str:
    params: dict[str, str] = dict(config.params)
    if config.truncation_limit:
        params["truncation_limit"] = str(config.truncation_limit)
    if should_use_incremental_field and db_incremental_field_last_value is not None and config.incremental_param:
        params[config.incremental_param] = _format_since_value(db_incremental_field_last_value)
    return f"{base_url}{config.path}?{urlencode(params)}"


def get_rows(
    api_server: str,
    username: str,
    password: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[QualysVmdrResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = QUALYS_VMDR_ENDPOINTS[endpoint]
    base_url = build_base_url(api_server)
    session = _make_session(username, password)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        url = resume.next_url
        logger.debug(f"Qualys VMDR: resuming from URL: {url}")
    else:
        url = _build_initial_url(base_url, config, should_use_incremental_field, db_incremental_field_last_value)

    while True:
        root = _fetch_page(session, url, logger)
        rows = list(_extract_rows(root, config))
        next_url = _next_batch_url(root, base_url)

        if rows:
            yield rows

        if not next_url:
            break

        # Save AFTER yielding so a crash re-yields the last batch (merge dedupes on the primary
        # key) rather than skipping it.
        resumable_source_manager.save_state(QualysVmdrResumeConfig(next_url=next_url))
        url = next_url


def validate_credentials(api_server: str, username: str, password: str) -> bool:
    """Cheap create-time probe: one host-list request capped at a single record.

    403 is accepted — the credential authenticated but lacks the asset-listing scope; per-table
    scope problems surface at sync time. 409 (rate/concurrency limited) also proves the
    credential is genuine.
    """
    base_url = build_base_url(api_server)
    url = f"{base_url}/api/2.0/fo/asset/host/?{urlencode({'action': 'list', 'truncation_limit': 1})}"
    try:
        response = _make_session(username, password).get(url, timeout=30)
        return response.status_code in (200, 403, 409)
    except Exception:
        return False


def qualys_vmdr_source(
    api_server: str,
    username: str,
    password: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[QualysVmdrResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = QUALYS_VMDR_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_server=api_server,
            username=username,
            password=password,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Batches are ordered by record id (id_min paging), not by the incremental datetime, so
        # the watermark must only persist at successful job end — never per batch.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
