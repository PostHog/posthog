import dataclasses
from collections.abc import Callable, Iterator
from datetime import date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.surveysparrow.settings import (
    SURVEYSPARROW_ENDPOINTS,
    SurveySparrowEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
# Page size used when enumerating survey ids for fan-out endpoints (/v3/surveys caps at 100).
SURVEY_LIST_PAGE_SIZE = 100


class SurveySparrowRetryableError(Exception):
    """Raised for 429 / 5xx responses so tenacity retries with backoff."""


@dataclasses.dataclass
class SurveySparrowResumeConfig:
    # Page currently being fetched. Checkpointed after its rows are yielded, so a resume
    # re-fetches (and re-yields) that page rather than skipping rows the pipeline may not have
    # flushed yet; merge dedupes on the primary key.
    page: int = 1
    # Surveys not yet fully processed (fan-out only). The head of the list is the survey
    # currently being read at `page`.
    remaining_survey_ids: Optional[list[int]] = None


def _get_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _format_cutoff(value: Any) -> str:
    """Format the incremental watermark for SurveySparrow's date filters.

    The docs only specify `YYYY-MM-DD` dates for these filters, so the watermark is floored to
    its day: each incremental sync re-fetches up to one day of overlap, which merge dedupes.
    """
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _build_params(
    config: SurveySparrowEndpointConfig,
    page: int,
    cutoff: str | None = None,
    survey_id: int | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": config.page_size, "page": page, **config.extra_params}
    if survey_id is not None:
        params["survey_id"] = survey_id
    if cutoff and config.cutoff_param:
        params[config.cutoff_param] = cutoff
    return params


def _attach_survey_id(item: dict[str, Any], survey_id: int) -> dict[str, Any]:
    row = dict(item)
    # Rows already carry survey_id per the docs, but the composite primary key must never be
    # null, so stamp it from the fan-out loop regardless.
    row["survey_id"] = survey_id
    return row


def validate_credentials(access_token: str, base_url: str) -> tuple[bool, str | None]:
    """Cheap probe against `/v3/surveys` to confirm the token is genuine for this data center."""
    session = make_tracked_session(headers=_get_headers(access_token), redact_values=(access_token,))
    try:
        response = session.get(f"{base_url}/v3/surveys", params={"limit": 1}, timeout=15)
    except requests.exceptions.RequestException as e:
        return False, f"Could not connect to SurveySparrow: {e}"

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return (
            False,
            "Invalid SurveySparrow access token. Check the token and that the data center matches your account.",
        )
    if response.status_code == 403:
        return False, "Your SurveySparrow access token is missing the required scopes."

    return False, f"SurveySparrow API returned status {response.status_code}"


def get_rows(
    access_token: str,
    base_url: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SurveySparrowResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = SURVEYSPARROW_ENDPOINTS[endpoint]
    # One session reused across the whole sync. urllib3 retries are disabled so tenacity below
    # is the single retry authority.
    session = make_tracked_session(
        headers=_get_headers(access_token), retry=Retry(total=0), redact_values=(access_token,)
    )

    cutoff = (
        _format_cutoff(db_incremental_field_last_value)
        if should_use_incremental_field and db_incremental_field_last_value
        else None
    )

    @retry(
        retry=retry_if_exception_type((SurveySparrowRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(path: str, params: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
        response = session.get(f"{base_url}{path}", params=params, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise SurveySparrowRetryableError(
                f"SurveySparrow API error (retryable): status={response.status_code}, path={path}"
            )

        if not response.ok:
            logger.error(f"SurveySparrow API error: status={response.status_code}, body={response.text}, path={path}")
            response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise SurveySparrowRetryableError(f"SurveySparrow returned an unexpected payload for {path}")

        # Some list endpoints (e.g. /v3/contact_lists) don't document has_next_page; a missing
        # flag means the page is the last one.
        return payload["data"], bool(payload.get("has_next_page"))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.is_fanout:
        yield from _iter_fanout(config, cutoff, fetch_page, resumable_source_manager, resume, logger)
    else:
        yield from _iter_top_level(config, cutoff, fetch_page, resumable_source_manager, resume)


FetchPage = Callable[[str, dict[str, Any]], tuple[list[dict[str, Any]], bool]]


def _iter_top_level(
    config: SurveySparrowEndpointConfig,
    cutoff: str | None,
    fetch_page: FetchPage,
    manager: ResumableSourceManager[SurveySparrowResumeConfig],
    resume: SurveySparrowResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    page = resume.page if resume else 1

    while True:
        items, has_next = fetch_page(config.path, _build_params(config, page, cutoff))
        if items:
            yield items
            manager.save_state(SurveySparrowResumeConfig(page=page))

        # An empty page also terminates defensively so a stale flag can never loop forever.
        if not has_next or not items:
            break
        page += 1


def _list_all_survey_ids(fetch_page: FetchPage) -> list[int]:
    """Enumerate every survey id by paging /v3/surveys (fan-out parents)."""
    survey_ids: list[int] = []
    page = 1
    while True:
        items, has_next = fetch_page("/v3/surveys", {"limit": SURVEY_LIST_PAGE_SIZE, "page": page})
        for item in items:
            # Direct access: a survey without an id is a malformed response, and silently
            # skipping it would drop all of that survey's child rows with no trace.
            survey_ids.append(int(item["id"]))
        if not has_next or not items:
            return survey_ids
        page += 1


def _iter_fanout(
    config: SurveySparrowEndpointConfig,
    cutoff: str | None,
    fetch_page: FetchPage,
    manager: ResumableSourceManager[SurveySparrowResumeConfig],
    resume: SurveySparrowResumeConfig | None,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    if resume and resume.remaining_survey_ids is not None:
        remaining = list(resume.remaining_survey_ids)
        page = resume.page
    else:
        remaining = _list_all_survey_ids(fetch_page)
        page = 1

    logger.debug(f"SurveySparrow: fanning out {config.name} across {len(remaining)} surveys")

    while remaining:
        survey_id = remaining[0]
        items, has_next = fetch_page(config.path, _build_params(config, page, cutoff, survey_id=survey_id))

        if items:
            yield [_attach_survey_id(item, survey_id) for item in items]
            manager.save_state(SurveySparrowResumeConfig(page=page, remaining_survey_ids=remaining))

        if has_next and items:
            page += 1
        else:
            remaining = remaining[1:]
            page = 1


def surveysparrow_source(
    access_token: str,
    base_url: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SurveySparrowResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SURVEYSPARROW_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
            base_url=base_url,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
