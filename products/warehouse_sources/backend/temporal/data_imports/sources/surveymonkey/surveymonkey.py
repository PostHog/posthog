import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, time
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.surveymonkey.settings import (
    DEFAULT_PAGE_SIZE,
    SURVEYMONKEY_ENDPOINTS,
    SurveyMonkeyEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5


class SurveyMonkeyRetryableError(Exception):
    """Raised for 429 / 5xx responses so tenacity retries with backoff."""


@dataclasses.dataclass
class SurveyMonkeyResumeConfig:
    # For the top-level `surveys` endpoint: the current list page URL to re-fetch on resume.
    # For fan-out endpoints: the current child-resource page URL within the survey at the head
    # of `remaining_survey_ids`.
    next_url: Optional[str] = None
    # Surveys not yet fully processed (fan-out only). The head of the list is the survey
    # currently being read, so a resume re-reads it and relies on primary-key merge to dedupe.
    remaining_survey_ids: Optional[list[str]] = None


def _get_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _format_incremental_value(value: Any) -> str:
    """SurveyMonkey expects `YYYY-MM-DDTHH:MM:SS` (UTC, no offset) for its date filters."""
    if isinstance(value, datetime):
        utc_value = value.astimezone(UTC) if value.tzinfo is not None else value
        return utc_value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return datetime.combine(value, time.min).strftime("%Y-%m-%dT%H:%M:%S")
    return str(value)


def _cutoff_param_name(incremental_field: str | None, config: SurveyMonkeyEndpointConfig) -> str:
    """Map the chosen cursor field to its server-side filter param."""
    chosen = incremental_field or config.default_incremental_field
    if chosen == "date_created":
        return "start_created_at"
    return "start_modified_at"


def _build_list_url(
    base_url: str,
    config: SurveyMonkeyEndpointConfig,
    cutoff: str | None,
    incremental_field: str | None,
    survey_id: str | None = None,
) -> str:
    path = config.path.format(survey_id=survey_id) if survey_id is not None else config.path
    params: dict[str, Any] = {"per_page": config.page_size}

    # Pull the stable/cursor dates and counts that aren't returned on the bare survey object.
    if config.name == "surveys":
        params["include"] = "date_created,date_modified,response_count,question_count"

    # Sort ascending on the cursor field so the pipeline's watermark advances monotonically and
    # offset pagination stays stable as new rows arrive. Only endpoints with a server-side sort
    # enum set `sort_by`; the rest page via the `links.next` cursor in the API's default order.
    if config.sort_by:
        params["sort_by"] = config.sort_by
        params["sort_order"] = "ASC"

    if cutoff:
        params[_cutoff_param_name(incremental_field, config)] = cutoff

    return f"{base_url}{path}?{urlencode(params)}"


def validate_credentials(access_token: str, base_url: str) -> tuple[bool, str | None]:
    """Cheap probe against `/users/me` to confirm the token is genuine."""
    url = f"{base_url}/users/me"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(access_token), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid SurveyMonkey access token"
    if response.status_code == 403:
        return False, "SurveyMonkey access token is missing required scopes"

    try:
        message = response.json().get("error", {}).get("message")
    except (ValueError, AttributeError):
        message = None
    return False, message or f"SurveyMonkey API returned status {response.status_code}"


def _attach_survey_id(item: dict[str, Any], survey_id: str) -> dict[str, Any]:
    row = dict(item)
    row["survey_id"] = survey_id
    return row


def _extract_questions(details: dict[str, Any], survey_id: str) -> list[dict[str, Any]]:
    """Flatten the nested pages[].questions[] of a `/surveys/{id}/details` payload."""
    rows: list[dict[str, Any]] = []
    for page in details.get("pages", []) or []:
        page_id = page.get("id")
        for question in page.get("questions", []) or []:
            row = dict(question)
            row["survey_id"] = survey_id
            row["page_id"] = page_id
            rows.append(row)
    return rows


def get_rows(
    access_token: str,
    base_url: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SurveyMonkeyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = SURVEYMONKEY_ENDPOINTS[endpoint]
    # One session reused across the whole sync (keeps TLS/TCP connections warm). urllib3 retries
    # are disabled so tenacity below is the single retry authority — otherwise the two layers
    # multiply request counts against SurveyMonkey's low daily call quota.
    session = make_tracked_session(headers=_get_headers(access_token), retry=Retry(total=0))

    cutoff = (
        _format_incremental_value(db_incremental_field_last_value)
        if should_use_incremental_field and db_incremental_field_last_value
        else None
    )

    @retry(
        retry=retry_if_exception_type((SurveyMonkeyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = session.get(page_url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise SurveyMonkeyRetryableError(
                f"SurveyMonkey API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"SurveyMonkey API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.extract_questions_from_details:
        yield from _iter_questions(base_url, config, fetch_page, resumable_source_manager, resume, logger)
    elif config.is_fanout:
        yield from _iter_fanout(
            base_url, config, cutoff, incremental_field, fetch_page, resumable_source_manager, resume, logger
        )
    else:
        yield from _iter_top_level(
            base_url, config, cutoff, incremental_field, fetch_page, resumable_source_manager, resume
        )


def _list_all_survey_ids(
    base_url: str,
    fetch_page: Callable[[str], dict[str, Any]],
) -> list[str]:
    """Enumerate every survey id by paging `/surveys` (ids only; no include/filter)."""
    survey_ids: list[str] = []
    url: str | None = f"{base_url}/surveys?{urlencode({'per_page': DEFAULT_PAGE_SIZE})}"
    while url:
        page = fetch_page(url)
        for item in page.get("data", []) or []:
            # Direct access: a survey without an id is a malformed response, and silently
            # skipping it would drop all of that survey's child records (pages, questions,
            # responses, collectors) with no trace. Fail loudly instead.
            survey_ids.append(str(item["id"]))
        url = page.get("links", {}).get("next")
    return survey_ids


def _iter_top_level(
    base_url: str,
    config: SurveyMonkeyEndpointConfig,
    cutoff: str | None,
    incremental_field: str | None,
    fetch_page: Callable[[str], dict[str, Any]],
    manager: ResumableSourceManager[SurveyMonkeyResumeConfig],
    resume: SurveyMonkeyResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    url: str | None = (
        resume.next_url if resume and resume.next_url else _build_list_url(base_url, config, cutoff, incremental_field)
    )

    while url:
        page = fetch_page(url)
        items = page.get("data", []) or []
        next_url = page.get("links", {}).get("next")

        if items:
            yield items
            # Checkpoint the page we just yielded (not the next one) so a crash re-yields it
            # rather than skipping rows the pipeline may not have flushed yet.
            manager.save_state(SurveyMonkeyResumeConfig(next_url=url))

        url = next_url


def _iter_fanout(
    base_url: str,
    config: SurveyMonkeyEndpointConfig,
    cutoff: str | None,
    incremental_field: str | None,
    fetch_page: Callable[[str], dict[str, Any]],
    manager: ResumableSourceManager[SurveyMonkeyResumeConfig],
    resume: SurveyMonkeyResumeConfig | None,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    if resume and resume.remaining_survey_ids is not None:
        remaining = list(resume.remaining_survey_ids)
        current_url = resume.next_url
    else:
        remaining = _list_all_survey_ids(base_url, fetch_page)
        current_url = None

    logger.debug(f"SurveyMonkey: fanning out {config.name} across {len(remaining)} surveys")

    while remaining:
        survey_id = remaining[0]
        if current_url is None:
            current_url = _build_list_url(base_url, config, cutoff, incremental_field, survey_id=survey_id)

        page = fetch_page(current_url)
        items = page.get("data", []) or []
        next_url = page.get("links", {}).get("next")

        if items:
            yield [_attach_survey_id(item, survey_id) for item in items]
            manager.save_state(SurveyMonkeyResumeConfig(next_url=current_url, remaining_survey_ids=remaining))

        if next_url:
            current_url = next_url
        else:
            remaining = remaining[1:]
            current_url = None


def _iter_questions(
    base_url: str,
    config: SurveyMonkeyEndpointConfig,
    fetch_page: Callable[[str], dict[str, Any]],
    manager: ResumableSourceManager[SurveyMonkeyResumeConfig],
    resume: SurveyMonkeyResumeConfig | None,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    if resume and resume.remaining_survey_ids is not None:
        remaining = list(resume.remaining_survey_ids)
    else:
        remaining = _list_all_survey_ids(base_url, fetch_page)

    logger.debug(f"SurveyMonkey: extracting questions across {len(remaining)} surveys")

    while remaining:
        survey_id = remaining[0]
        details = fetch_page(f"{base_url}{config.path.format(survey_id=survey_id)}")
        questions = _extract_questions(details, survey_id)
        if questions:
            yield questions

        remaining = remaining[1:]
        # Checkpoint with the current survey already dropped — the `/details` call is idempotent,
        # so on resume we continue with the next survey.
        manager.save_state(SurveyMonkeyResumeConfig(remaining_survey_ids=remaining))


def surveymonkey_source(
    access_token: str,
    base_url: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SurveyMonkeyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = SURVEYMONKEY_ENDPOINTS[endpoint]

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
            incremental_field=incremental_field,
        ),
        primary_keys=[config.primary_key],
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
