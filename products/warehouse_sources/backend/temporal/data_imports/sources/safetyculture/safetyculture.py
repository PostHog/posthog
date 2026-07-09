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
from products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.settings import (
    SAFETYCULTURE_ENDPOINTS,
    SafetyCultureEndpointConfig,
)

SAFETYCULTURE_BASE_URL = "https://api.safetyculture.io"
REQUEST_TIMEOUT_SECONDS = 60
# Cheap feed used to confirm an API token is genuine. Feed access is permission-scoped, so a 403
# here still proves the token itself is valid (see `validate_credentials` on the source class).
DEFAULT_PROBE_PATH = "/feed/users"


class SafetyCultureRetryableError(Exception):
    pass


@dataclasses.dataclass
class SafetyCultureResumeConfig:
    # Path of the next page to fetch, taken verbatim from the API's `metadata.next_page` (the docs
    # forbid constructing it yourself). It embeds every filter — including `modified_after` on an
    # incremental sync — so a crashed sync resumes from the page after the last one yielded; merge
    # dedupes the re-pulled page on `id`.
    next_page: str | None = None


def _headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_token}", "Accept": "application/json"}


def _format_modified_after(value: Any) -> str:
    """Format an incremental cursor as the Internet Date-Time string SafetyCulture expects.

    Since 2025-02-01 the Feed APIs reject anything that isn't `{Y}-{m}-{d}T{H}:{M}:{S}[.{frac}]Z`.
    """
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return str(value)


def _build_initial_path(
    config: SafetyCultureEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> str:
    params = dict(config.params)
    if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value:
        params["modified_after"] = _format_modified_after(db_incremental_field_last_value)
    if not params:
        return config.path
    return f"{config.path}?{urlencode(params)}"


def _extract_next_page(data: dict[str, Any]) -> Optional[str]:
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        return None
    next_page = metadata.get("next_page")
    return next_page if isinstance(next_page, str) and next_page else None


@retry(
    retry=retry_if_exception_type((SafetyCultureRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    logger: FilteringBoundLogger,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    # `path` is either the initial endpoint path or a verbatim `metadata.next_page`, so we never
    # re-send query params — they're baked into the path.
    url = f"{SAFETYCULTURE_BASE_URL}{path}"
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    # SafetyCulture rate-limits with 429 on all endpoints; transient 5xx are retryable too.
    if response.status_code == 429 or response.status_code >= 500:
        raise SafetyCultureRetryableError(
            f"SafetyCulture API error (retryable): status={response.status_code}, path={path}"
        )

    if not response.ok:
        logger.error(f"SafetyCulture API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    # Every data feed wraps records in {"metadata": {"next_page", "remaining_records"}, "data": [...]}.
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise SafetyCultureRetryableError(
            f"SafetyCulture returned an unexpected payload for {path}: {type(data).__name__}"
        )

    return data["data"], _extract_next_page(data)


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SafetyCultureResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = SAFETYCULTURE_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    path = (
        resume.next_page
        if (resume and resume.next_page)
        else _build_initial_path(config, should_use_incremental_field, db_incremental_field_last_value)
    )
    if resume and resume.next_page:
        logger.debug(f"SafetyCulture: resuming {endpoint} from {path}")

    while True:
        items, next_page = _fetch_page(session, path, logger)
        if items:
            yield items

        # A null `next_page` marks the end of the feed. An empty page also terminates defensively so
        # a lingering cursor can never produce an infinite loop.
        if not next_page or not items:
            break

        path = next_page
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(SafetyCultureResumeConfig(next_page=next_page))


def safetyculture_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SafetyCultureResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SAFETYCULTURE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Incremental feeds paginate by advancing `modified_after` in the server-issued `next_page`
        # path, so rows arrive oldest-modified-first — matching the pipeline's ascending watermark.
        sort_mode="asc",
    )


def check_access(api_token: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single feed to validate the API token.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))
    try:
        response = session.get(f"{SAFETYCULTURE_BASE_URL}{path}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to SafetyCulture: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"SafetyCulture returned HTTP {response.status_code}"

    return 200, None
