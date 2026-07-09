import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.bland_ai.settings import BLAND_AI_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# The authorization header is the raw API key (no "Bearer" prefix).
BASE_URL = "https://api.bland.ai"

# GET /v1/calls default (and documented maximum) page size.
PAGE_SIZE = 1000

REQUEST_TIMEOUT_SECONDS = 60


class BlandAIRetryableError(Exception):
    pass


@dataclasses.dataclass
class BlandAIResumeConfig:
    # Index offset into the call list (`from` query param) of the next unfetched page.
    offset: int = 0
    # The exact `start_date` filter the interrupted run used. The pipeline checkpoints the
    # incremental watermark per batch, so on resume `db_incremental_field_last_value` may already
    # have advanced past the value we filtered by — reusing the original filter keeps the saved
    # offset pointing into the same result set.
    start_date: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "authorization": api_key,
        "Accept": "application/json",
    }


@retry(
    retry=retry_if_exception_type(
        (BlandAIRetryableError, requests.ReadTimeout, requests.ConnectionError),
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> Any:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    # Bland's read-endpoint rate limits aren't documented, so back off politely on 429 and 5xx.
    if response.status_code == 429 or response.status_code >= 500:
        raise BlandAIRetryableError(f"Bland AI API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Bland AI API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> bool:
    # Cheapest probe that exercises the token: list a single call. A bad key returns
    # 401 {"errors": [{"error": "AUTH_FAILURE", ...}]}.
    url = f"{BASE_URL}/v1/calls?{urlencode({'limit': 1})}"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _format_start_date(value: Any) -> str | None:
    """Format the incremental watermark as the ISO 8601 value `start_date` accepts.

    A naive datetime is stamped UTC — Bland interprets offset-less values as UTC anyway, and an
    explicit offset guards against that default changing.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _get_pathway_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    data = _fetch(session, f"{BASE_URL}/v1/pathway", headers, logger)

    # The docs' response example shows a single pathway object without an explicit list wrapper,
    # and we couldn't verify the live shape without account credentials — accept a bare list,
    # common list wrappers, or a single object.
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        wrapped = next((data[key] for key in ("pathways", "data") if isinstance(data.get(key), list)), None)
        rows = wrapped if wrapped is not None else [data]
    else:
        rows = []

    if rows:
        yield rows


def _transcript_rows(
    session: requests.Session,
    headers: dict[str, str],
    calls: list[dict[str, Any]],
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for call in calls:
        detail = _fetch(session, f"{BASE_URL}/v1/calls/{call['call_id']}", headers, logger)
        for utterance in detail.get("transcripts") or []:
            rows.append(
                {
                    **utterance,
                    "call_id": call["call_id"],
                    # The parent call's creation time. Utterance `created_at`s aren't monotonic
                    # across calls (a long call's utterances postdate the next call's creation),
                    # so this is the field the incremental cursor and partitioning key off.
                    # Direct access on purpose: a silent None here would corrupt partitions and
                    # stall the incremental watermark.
                    "call_created_at": call["created_at"],
                }
            )
    return rows


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BlandAIResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> Iterator[list[dict[str, Any]]]:
    config = BLAND_AI_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across every list page and hydration request so urllib3 keeps the
    # connection alive instead of re-handshaking per request.
    session = make_tracked_session()

    if endpoint == "pathways":
        yield from _get_pathway_rows(session, headers, logger)
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        offset = resume.offset
        start_date = resume.start_date
        logger.debug(f"Bland AI: resuming {endpoint} from offset {offset} (start_date={start_date})")
    else:
        offset = 0
        start_date = _format_start_date(db_incremental_field_last_value) if should_use_incremental_field else None

    while True:
        params: dict[str, Any] = {
            "from": offset,
            "limit": PAGE_SIZE,
            # Ascending creation order so the pipeline's incremental watermark can checkpoint
            # after every batch, and so index offsets stay stable while new calls append.
            "ascending": "true",
            "sort_by": "created_at",
        }
        if start_date:
            # `start_date` is inclusive; the boundary row is re-fetched and deduped by merge.
            params["start_date"] = start_date
        data = _fetch(session, f"{BASE_URL}/v1/calls?{urlencode(params)}", headers, logger)

        calls = data.get("calls") or []
        if not calls:
            break

        rows = _transcript_rows(session, headers, calls, logger) if config.hydrate_transcripts else calls
        if rows:
            yield rows

        offset += len(calls)
        total_count = data.get("total_count")
        if isinstance(total_count, int) and offset >= total_count:
            break

        # Save AFTER yielding the page so a crash re-yields the just-finished page rather than
        # skipping it — merge dedupes on the primary key. Resume picks up at the next offset.
        resumable_source_manager.save_state(BlandAIResumeConfig(offset=offset, start_date=start_date))


def bland_ai_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BlandAIResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = BLAND_AI_ENDPOINTS[endpoint]

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
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        # Call endpoints request `ascending=true&sort_by=created_at`; pathways is a single
        # unordered page on a full-refresh-only endpoint, so the value never drives a watermark.
        sort_mode="asc",
    )
