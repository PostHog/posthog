import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.shippo.settings import SHIPPO_ENDPOINTS

SHIPPO_BASE_URL = "https://api.goshippo.com"
# List endpoints cap `results` at 100 (values over 200 truncate); the largest page minimises
# round trips against Shippo's tight GET-list rate limit (50/min live, 10/min test).
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 7
# Shippo rejects creation-date ranges wider than 90 days, so incremental syncs walk the
# watermark forward in windows kept safely under that cap.
CREATED_FILTER_WINDOW = timedelta(days=89)
# Cheap probe used to confirm an API token is genuine. The token is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/shipments"


class ShippoRetryableError(Exception):
    pass


@dataclasses.dataclass
class ShippoResumeConfig:
    # Opaque `next` URL of the page to fetch next; Shippo documents these links as subject to
    # change in format, so we follow them verbatim rather than reconstructing page numbers.
    next_url: str | None = None
    # ISO timestamp of the creation-date window currently being walked (incremental shipments
    # syncs only). `None` for unfiltered full-catalog pagination.
    window_start: str | None = None


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"ShippoToken {api_key}", "Accept": "application/json"}


def _format_datetime(value: datetime) -> str:
    # Shippo's date filters take ISO 8601 UTC without offsets; truncating to whole seconds only
    # ever widens the exclusive lower bound, and merge dedupes any re-pulled rows.
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return None


def _build_url(path: str, params: dict[str, Any]) -> str:
    clean_params = {key: value for key, value in params.items() if value is not None}
    return f"{SHIPPO_BASE_URL}{path}/?{urlencode(clean_params)}"


@retry(
    retry=retry_if_exception_type((ShippoRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=5, max=90),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict[str, Any]:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    # Shippo rate limits per method per minute (GET-list is only 50/min live, 10/min test), so
    # the backoff must be generous enough to cross into the next minute window.
    if response.status_code == 429 or response.status_code >= 500:
        raise ShippoRetryableError(f"Shippo API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Shippo API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    # Shippo list endpoints wrap records in {"next": url|null, "previous": url|null, "results": [...]}.
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ShippoRetryableError(f"Shippo returned an unexpected payload for {url}: {type(data).__name__}")

    return data


def _paginate(
    session: requests.Session,
    first_url: str,
    window_start: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ShippoResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    url: str | None = first_url
    while url:
        data = _fetch_page(session, url, logger)
        items: list[dict[str, Any]] = data["results"]
        if items:
            yield items

        url = data.get("next") or None
        if url:
            # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages
            # are persisted); merge dedupes the re-pulled page on the primary key.
            resumable_source_manager.save_state(ShippoResumeConfig(next_url=url, window_start=window_start))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ShippoResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = SHIPPO_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    watermark = _parse_datetime(db_incremental_field_last_value) if should_use_incremental_field else None

    if watermark is not None and config.supports_created_filter:
        # Walk forward from the watermark in sub-90-day creation-date windows (Shippo rejects
        # wider ranges). Note Shippo does not return shipments older than 390 days, which bounds
        # how far back the very first sync can reach regardless of windowing.
        now = datetime.now(UTC)
        resume_url: str | None = None
        if resume is not None and resume.window_start is not None:
            resumed_start = _parse_datetime(resume.window_start)
            if resumed_start is not None:
                watermark = resumed_start
                resume_url = resume.next_url
                logger.debug(f"Shippo: resuming {endpoint} window {resume.window_start} from {resume_url}")

        window_start = watermark
        while window_start < now:
            window_end = min(window_start + CREATED_FILTER_WINDOW, now)
            start_iso = _format_datetime(window_start)
            if resume_url is not None:
                first_url, resume_url = resume_url, None
            else:
                first_url = _build_url(
                    config.path,
                    {
                        "results": PAGE_SIZE,
                        "object_created_gt": start_iso,
                        "object_created_lte": _format_datetime(window_end),
                    },
                )
            yield from _paginate(session, first_url, start_iso, logger, resumable_source_manager)

            window_start = window_end
            resumable_source_manager.save_state(
                ShippoResumeConfig(next_url=None, window_start=_format_datetime(window_start))
            )
    else:
        if resume is not None and resume.next_url is not None and resume.window_start is None:
            first_url = resume.next_url
            logger.debug(f"Shippo: resuming {endpoint} from {first_url}")
        else:
            first_url = _build_url(config.path, {"results": PAGE_SIZE})
        yield from _paginate(session, first_url, None, logger, resumable_source_manager)


def shippo_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ShippoResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SHIPPO_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # Shippo does not document (or accept a param controlling) list ordering, so we
        # conservatively treat responses as unordered: "desc" defers the incremental watermark
        # commit to the end of a successful run instead of checkpointing per batch.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def check_access(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API token.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(f"{SHIPPO_BASE_URL}{path}/?{urlencode({'results': 1})}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Shippo: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Shippo returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Shippo API token"
    return False, message or "Could not validate Shippo API token"
