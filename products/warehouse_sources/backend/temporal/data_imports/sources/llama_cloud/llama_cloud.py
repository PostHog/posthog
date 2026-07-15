import dataclasses
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.llama_cloud.settings import (
    DEFAULT_LLAMA_CLOUD_REGION,
    LLAMA_CLOUD_ENDPOINTS,
    LLAMA_CLOUD_REGIONS,
    LlamaCloudEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60


class LlamaCloudRetryableError(Exception):
    pass


def _project_rows(rows: list[dict[str, Any]], allowed_fields: frozenset[str]) -> list[dict[str, Any]]:
    """Keep only allowlisted top-level keys on each row.

    LlamaCloud pipeline definitions embed third-party credentials — embedding-provider
    API keys, data-sink connection secrets, bearer tokens — in nested config objects.
    Projecting onto the documented, non-sensitive fields keeps those secrets out of the
    warehouse structurally, rather than trying to enumerate every secret-bearing key.
    """
    return [{key: value for key, value in row.items() if key in allowed_fields} for row in rows]


@dataclasses.dataclass
class LlamaCloudResumeConfig:
    next_page_token: str


def get_base_url(region: str | None) -> str:
    normalized_region = (region or DEFAULT_LLAMA_CLOUD_REGION).lower()
    if normalized_region not in LLAMA_CLOUD_REGIONS:
        raise ValueError(f"LlamaCloud region must be one of {', '.join(sorted(LLAMA_CLOUD_REGIONS))}")
    return LLAMA_CLOUD_REGIONS[normalized_region]


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def _format_datetime(value: Any) -> str:
    """Format the incremental watermark for `created_at_on_or_after`.

    Truncates to whole seconds, rounding the inclusive lower bound *down* — a sync
    re-fetches at most a few boundary rows (merge dedupes them) rather than skipping any.
    """
    normalized_value = coerce_datetime_to_utc(value)
    if normalized_value is None:
        return str(value)
    return normalized_value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_day(value: Any) -> str:
    """Format the incremental watermark for `day_on_or_after` (a plain YYYY-MM-DD date)."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _format_incremental_value(config: LlamaCloudEndpointConfig, value: Any) -> str:
    if config.incremental_param == "day_on_or_after":
        return _format_day(value)
    return _format_datetime(value)


@retry(
    retry=retry_if_exception_type(
        (
            LlamaCloudRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], params: dict[str, Any]) -> Any:
    # The tracked session's urllib3 retry already backs off on 429/5xx honoring Retry-After;
    # this tenacity layer catches what slips through once those retries are exhausted.
    response = session.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise LlamaCloudRetryableError(f"LlamaCloud API error (retryable): status={response.status_code}, url={url}")

    response.raise_for_status()

    return response.json()


def _parse_error_detail(response: requests.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, str) and detail:
                return detail
    except Exception:
        pass
    return response.text


def validate_credentials(api_key: str, region: str | None = None) -> tuple[bool, str | None]:
    try:
        base_url = get_base_url(region)
    except ValueError as exc:
        return False, str(exc)

    try:
        response = make_tracked_session().get(
            f"{base_url}/api/v2/projects",
            headers=_headers(api_key),
            params={"page_size": 1},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        return False, f"Could not reach the LlamaCloud API: {exc}"

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        # LlamaCloud keys are project-scoped with no finer-grained scopes, and its 401 body
        # already points at the most common cause (a key from the other region).
        return False, f"Invalid LlamaCloud API key: {_parse_error_detail(response)}"
    return False, f"LlamaCloud API returned an unexpected error: {_parse_error_detail(response)}"


def _resolve_organization_id(session: requests.Session, base_url: str, headers: dict[str, str]) -> str:
    """Resolve the organization id the usage-metrics endpoint requires.

    The API key is project-scoped, so the projects it can list all belong to the key's
    organization — the first project's organization_id is the right one.
    """
    data = _fetch_page(session, f"{base_url}/api/v2/projects", headers, {"page_size": 1})
    items = data.get("items") or []
    organization_id = items[0].get("organization_id") if items else None
    if not organization_id:
        raise ValueError("Could not resolve the LlamaCloud organization id from the API key's project")
    return organization_id


def get_rows(
    api_key: str,
    region: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LlamaCloudResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = LLAMA_CLOUD_ENDPOINTS[endpoint]
    base_url = get_base_url(region)
    url = f"{base_url}{config.path}"
    headers = _headers(api_key)
    # One session reused across every page so urllib3 keeps the connection alive.
    # Endpoints whose raw responses carry secrets opt out of HTTP sample capture — the
    # sampler observes the upstream body before row projection runs.
    session = make_tracked_session(capture=config.capture_http_samples)

    if not config.paginated:
        data = _fetch_page(session, url, headers, {})
        if data:
            yield _project_rows(data, config.output_fields) if config.output_fields else data
        return

    params: dict[str, Any] = {"page_size": config.page_size}

    if config.requires_organization_id:
        params["organization_id"] = _resolve_organization_id(session, base_url, headers)

    # Every endpoint advertises at most one incremental field, so the endpoint's filter
    # param maps directly to the user's chosen cursor field.
    if should_use_incremental_field and config.incremental_param and db_incremental_field_last_value is not None:
        params[config.incremental_param] = _format_incremental_value(config, db_incremental_field_last_value)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None and resume_config.next_page_token:
        params["page_token"] = resume_config.next_page_token
        logger.debug(f"LlamaCloud: resuming {endpoint} from page_token={resume_config.next_page_token}")

    while True:
        data = _fetch_page(session, url, headers, params)

        items = data.get("items") or []
        next_page_token = data.get("next_page_token")

        if items:
            yield _project_rows(items, config.output_fields) if config.output_fields else items

        if not next_page_token:
            break

        # Save AFTER yielding so a crash re-yields the last page rather than skipping it —
        # merge dedupes the re-yielded rows on the primary key.
        resumable_source_manager.save_state(LlamaCloudResumeConfig(next_page_token=next_page_token))
        params["page_token"] = next_page_token


def llama_cloud_source(
    api_key: str,
    region: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LlamaCloudResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = LLAMA_CLOUD_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            region=region,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # The list endpoints accept no sort param and don't document their ordering, so we
        # can't guarantee ascending rows. "desc" makes the pipeline persist the incremental
        # watermark (the max value seen) only after the sync completes, which is correct
        # regardless of the actual server order; page_token resume covers interruptions.
        sort_mode="desc" if config.incremental_param else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
