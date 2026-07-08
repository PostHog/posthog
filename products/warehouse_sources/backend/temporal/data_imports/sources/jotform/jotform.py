import json
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.jotform.settings import (
    JOTFORM_ENDPOINTS,
    JotformEndpointConfig,
)

# Regional API hosts. Enterprise installations live on the org's own domain (see resolve_base_url).
JOTFORM_REGION_BASE_URLS = {
    "us": "https://api.jotform.com",
    "eu": "https://eu-api.jotform.com",
    "hipaa": "https://hipaa-api.jotform.com",
}

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
# Jotform's `filter` operator for "created/updated after" is `:gt` (strictly greater than).
FILTER_GT_SUFFIX = ":gt"


class JotformRetryableError(Exception):
    pass


@dataclasses.dataclass
class JotformResumeConfig:
    # Offset of the page to (re)fetch when resuming a list endpoint. Saved as the offset of the page
    # just yielded so a crash re-yields that page (merge dedupes on the primary key) instead of
    # skipping it.
    offset: int = 0
    # Form currently being processed by the questions fan-out. A stable form-id bookmark so a crash
    # resumes that form rather than a positional index that shifts as forms are added/removed.
    form_id: Optional[str] = None


def normalize_enterprise_host(enterprise_domain: Optional[str]) -> Optional[str]:
    host = (enterprise_domain or "").strip()
    if not host:
        return None
    host = host.removeprefix("https://").removeprefix("http://").strip("/")
    return host or None


def resolve_base_url(region: Optional[str], enterprise_domain: Optional[str] = None) -> str:
    host = normalize_enterprise_host(enterprise_domain)
    if host is not None:
        # Jotform Enterprise serves its API under `/API` on the organisation's own domain. Couldn't
        # be curl-verified without an Enterprise account, so this path is best-effort.
        return f"https://{host}/API"
    return JOTFORM_REGION_BASE_URLS.get((region or "us").lower(), JOTFORM_REGION_BASE_URLS["us"])


def _headers(api_key: str) -> dict[str, str]:
    # Jotform accepts the API key either as the `APIKEY` header or an `apiKey` query param. The
    # header keeps the secret out of request URLs (and out of logs).
    return {"APIKEY": api_key, "Accept": "application/json"}


def _coerce_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


def _format_filter_value(value: Any) -> Optional[str]:
    """Format an incremental cursor as Jotform's ``YYYY-MM-DD HH:MM:SS`` filter literal.

    Future-dated cursors are capped at now: a ``<field>:gt <future>`` filter returns nothing and
    would wedge the sync until wall-clock catches up. The watermark and the API's ``created_at`` /
    ``updated_at`` come from the same field round-tripped, so the wall-clock components line up.
    """
    parsed = _coerce_datetime(value)
    if parsed is None:
        return None
    aware = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    capped = min(aware, datetime.now(UTC))
    return capped.strftime("%Y-%m-%d %H:%M:%S")


def _build_list_params(
    config: JotformEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: Optional[str],
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if not config.incremental_fields:
        # Full-refresh endpoints (reports): no orderby/filter. Jotform doesn't document an orderby
        # enum for these, and they're small enough that offset stability isn't a concern.
        return params

    field_name = incremental_field or config.default_incremental_field
    # Order by the cursor field so pages arrive oldest-first and the asc watermark advances
    # correctly. Jotform's `orderby` sorts ascending by the given field (per the API docs; couldn't
    # be curl-verified without an API key).
    if field_name:
        params["orderby"] = field_name
        if should_use_incremental_field and db_incremental_field_last_value is not None:
            formatted = _format_filter_value(db_incremental_field_last_value)
            if formatted is not None:
                params["filter"] = json.dumps({f"{field_name}{FILTER_GT_SUFFIX}": formatted}, separators=(",", ":"))
    return params


@retry(
    retry=retry_if_exception_type((JotformRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_page(url: str, params: dict[str, Any], headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    # `enterprise_domain` is user-supplied, so pin redirects off (defense-in-depth on top of the
    # Smokescreen egress proxy, which is the load-bearing SSRF control) to keep the API-key-bearing
    # request on the validated host, and value-redact the key carried in the `APIKEY` header.
    api_key = headers.get("APIKEY")
    session = make_tracked_session(redact_values=(api_key,) if api_key else (), allow_redirects=False)
    response = session.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    # Jotform enforces daily call quotas rather than per-second rate limits; an exhausted quota or a
    # transient server error is worth retrying. Auth failures (401/403) are not — they surface to
    # `get_non_retryable_errors` and stop the sync.
    if response.status_code == 429 or response.status_code >= 500:
        raise JotformRetryableError(f"Jotform API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Jotform API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str, region: Optional[str], enterprise_domain: Optional[str] = None) -> bool:
    """Confirm the API key is valid for the target host. ``/user`` is the cheapest authenticated probe."""
    try:
        # Same SSRF posture as `_fetch_page`: no redirects off the validated host, redact the key.
        response = make_tracked_session(redact_values=(api_key,), allow_redirects=False).get(
            f"{resolve_base_url(region, enterprise_domain)}/user",
            headers=_headers(api_key),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_form_ids(base_url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> list[str]:
    config = JOTFORM_ENDPOINTS["forms"]
    ids: list[str] = []
    offset = 0

    while True:
        params = {"limit": config.page_size, "offset": offset, "orderby": "created_at"}
        data = _fetch_page(f"{base_url}{config.path}", params, headers, logger)
        content = data.get("content")
        if not isinstance(content, list) or not content:
            break

        ids.extend(str(item["id"]) for item in content if isinstance(item, dict) and item.get("id") is not None)

        if len(content) < config.page_size:
            break
        offset += config.page_size

    return ids


def _question_row(form_id: str, question: dict[str, Any]) -> dict[str, Any]:
    row = dict(question)
    # `qid` is unique only within a form, so every row carries the form id for a table-wide key.
    row["form_id"] = form_id
    return row


def _iter_list_pages(
    base_url: str,
    config: JotformEndpointConfig,
    headers: dict[str, str],
    base_params: dict[str, Any],
    manager: ResumableSourceManager[JotformResumeConfig],
    start_offset: int,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    offset = start_offset

    while True:
        params = {**base_params, "limit": config.page_size, "offset": offset}
        data = _fetch_page(f"{base_url}{config.path}", params, headers, logger)
        content = data.get("content")
        if not isinstance(content, list) or not content:
            break

        yield content

        # Save the offset of the page just yielded so a crash re-fetches and re-yields it (merge
        # dedupes on the primary key) rather than skipping it.
        manager.save_state(JotformResumeConfig(offset=offset))

        if len(content) < config.page_size:
            break
        offset += config.page_size


def _iter_questions(
    base_url: str,
    config: JotformEndpointConfig,
    headers: dict[str, str],
    manager: ResumableSourceManager[JotformResumeConfig],
    resume: Optional[JotformResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    form_ids = get_form_ids(base_url, headers, logger)

    remaining = form_ids
    if resume is not None and resume.form_id is not None and resume.form_id in form_ids:
        # Resume from the bookmarked form (re-fetched and re-yielded; merge dedupes). If the form was
        # deleted between runs, fall through and start over from the first form.
        remaining = form_ids[form_ids.index(resume.form_id) :]
        logger.debug(f"Jotform: resuming questions from form_id={resume.form_id}")

    for form_id in remaining:
        path = config.path.format(form_id=quote(str(form_id), safe=""))
        data = _fetch_page(f"{base_url}{path}", {}, headers, logger)
        content = data.get("content")

        # `/form/{id}/questions` returns an object keyed by question id, not a list.
        if isinstance(content, dict):
            rows = [_question_row(form_id, question) for question in content.values() if isinstance(question, dict)]
            if rows:
                yield rows

        # Bookmark the form just processed so a crash resumes here rather than skipping ahead.
        manager.save_state(JotformResumeConfig(form_id=form_id))


def get_rows(
    api_key: str,
    region: Optional[str],
    enterprise_domain: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JotformResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = JOTFORM_ENDPOINTS[endpoint]
    base_url = resolve_base_url(region, enterprise_domain)
    headers = _headers(api_key)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.fan_out_over_forms:
        yield from _iter_questions(base_url, config, headers, resumable_source_manager, resume, logger)
        return

    base_params = _build_list_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )
    start_offset = resume.offset if resume is not None else 0
    yield from _iter_list_pages(base_url, config, headers, base_params, resumable_source_manager, start_offset, logger)


def jotform_source(
    api_key: str,
    region: Optional[str],
    enterprise_domain: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JotformResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = JOTFORM_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            region=region,
            enterprise_domain=enterprise_domain,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=list(config.primary_keys),
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format=config.partition_format if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
