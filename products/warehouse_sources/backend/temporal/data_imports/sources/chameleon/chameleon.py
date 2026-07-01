import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.chameleon.settings import (
    CHAMELEON_ENDPOINTS,
    ChameleonEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# Single base URL for every account — Chameleon has no per-account hostname.
CHAMELEON_BASE_URL = "https://api.chameleon.io/v3"
# The account-secret probe hits the root, which echoes back the account/user ids on success.
CHAMELEON_ROOT_URL = "https://api.chameleon.io"


class ChameleonRetryableError(Exception):
    pass


@dataclasses.dataclass
class ChameleonResumeConfig:
    # Cursor for the next page: the `cursor.before` id from the previous response. None starts at page one.
    before: str | None = None
    # The Microsurvey currently being paged through, for the `responses` fan-out. A stable survey-id
    # bookmark (not a positional index) so surveys added/removed between a crash and the retry can't
    # resume us into the wrong survey. None for the standard (non-fan-out) endpoints.
    survey_id: str | None = None


def _get_headers(account_secret: str) -> dict[str, str]:
    return {"X-Account-Secret": account_secret, "Accept": "application/json"}


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


@retry(
    retry=retry_if_exception_type((ChameleonRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=60)

    # 429 (rate limited) and 5xx are transient — retry. Chameleon returns rate-limit wait hints in
    # X-Retry-After / X-Ratelimit-Wait headers; the exponential backoff below covers them conservatively.
    if response.status_code == 429 or response.status_code >= 500:
        raise ChameleonRetryableError(f"Chameleon API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # 404 is expected and handled during the responses fan-out (a survey deleted mid-sync).
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Chameleon API error: status={response.status_code}, body={response.text[:200]!r}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(account_secret: str) -> tuple[bool, str | None]:
    # The root probe echoes back the account/user ids on success (200). A bad or revoked secret is
    # rejected with 401/403 — those are the only conclusive "invalid" signals. Transport failures and
    # unexpected statuses (429, 5xx) are inconclusive: reporting them as an invalid secret would push
    # users to needlessly rotate a working credential, so they get a generic retry message instead.
    # `redact_values` masks the secret from any captured sample.
    try:
        response = make_tracked_session(redact_values=(account_secret,)).get(
            CHAMELEON_ROOT_URL, headers=_get_headers(account_secret), timeout=10
        )
    except requests.RequestException:
        return False, "Could not reach Chameleon to validate the account secret. Please try again."
    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid Chameleon account secret"
    return (
        False,
        f"Chameleon could not validate the account secret right now (status {response.status_code}). Please try again.",
    )


def _iter_pages(
    session: requests.Session,
    url: str,
    data_key: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    base_params: dict[str, Any],
    start_before: str | None,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    """Page a Chameleon list endpoint, yielding (rows, next_before) per page.

    Chameleon returns records newest-first and paginates with a `cursor.before` id pointing at the
    oldest record on the page; the next page is fetched with `before=<that id>`. Pagination stops once
    a page is empty, the cursor is exhausted, or the cursor fails to advance (a defensive guard against
    an unexpected repeated cursor wedging the sync in an infinite loop).
    """
    before = start_before
    while True:
        params = dict(base_params)
        if before:
            params["before"] = before

        data = _fetch_page(session, _build_url(url, params), headers, logger)
        rows = data.get(data_key, [])
        next_before = (data.get("cursor") or {}).get("before")

        yield rows, next_before

        if not rows or not next_before or next_before == before:
            break
        before = next_before


def _iter_survey_ids(session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger) -> Iterator[str]:
    config = CHAMELEON_ENDPOINTS["surveys"]
    for rows, _ in _iter_pages(
        session,
        f"{CHAMELEON_BASE_URL}{config.path}",
        config.data_key,
        headers,
        logger,
        {"limit": config.page_size},
        start_before=None,
    ):
        for survey in rows:
            yield survey["id"]


def _get_response_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ChameleonResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every Microsurvey, listing its responses and stamping the parent `survey_id`.

    /analyze/responses requires an `id` (the Microsurvey id), so responses can only be pulled per
    survey. Full refresh — re-pulled rows on resume are deduped by the `id` primary key on merge.
    """
    config = CHAMELEON_ENDPOINTS["responses"]
    survey_ids = list(_iter_survey_ids(session, headers, logger))

    # Resolve the saved survey-id bookmark to the slice of surveys still to process. If the bookmarked
    # survey no longer exists (deleted between runs), start over from the first survey — merge dedupes
    # the re-pulled rows on the primary key. `resume_before` is consumed by the first survey only.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = survey_ids
    resume_before: str | None = None
    if resume is not None and resume.survey_id is not None and resume.survey_id in survey_ids:
        remaining = survey_ids[survey_ids.index(resume.survey_id) :]
        resume_before = resume.before
        logger.debug(f"Chameleon: resuming responses from survey_id={resume.survey_id}, before={resume_before}")

    for index, survey_id in enumerate(remaining):
        start_before = resume_before
        resume_before = None  # only the resumed-into survey uses the saved cursor; the rest start fresh

        try:
            for rows, next_before in _iter_pages(
                session,
                f"{CHAMELEON_BASE_URL}{config.path}",
                config.data_key,
                headers,
                logger,
                {"id": survey_id, "limit": config.page_size},
                start_before,
            ):
                if rows:
                    yield [{**row, "survey_id": survey_id} for row in rows]
                    # Save AFTER yielding (and only when more pages remain) so a crash re-yields the
                    # last page rather than skipping it — merge dedupes on the primary key.
                    if next_before:
                        resumable_source_manager.save_state(
                            ChameleonResumeConfig(before=next_before, survey_id=survey_id)
                        )
        except requests.HTTPError as exc:
            # A survey deleted between enumeration and this fetch 404s. Skip it rather than failing the
            # whole sync — the responses are genuinely gone. Any other HTTP error is re-raised.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Chameleon: survey {survey_id} not found while fetching responses, skipping")
            else:
                raise

        # Advance the bookmark to the next survey so a crash between surveys resumes correctly.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(ChameleonResumeConfig(before=None, survey_id=remaining[index + 1]))


def get_rows(
    account_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ChameleonResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = CHAMELEON_ENDPOINTS[endpoint]
    headers = _get_headers(account_secret)
    # One session reused across every page (and, for fan-out, every survey) so urllib3 keeps the
    # connection alive instead of re-handshaking per request. The account secret rides in a custom
    # `X-Account-Secret` header the name-based scrubbers don't recognise, so redact it explicitly.
    session = make_tracked_session(redact_values=(account_secret,))

    if config.fan_out_over_surveys:
        yield from _get_response_rows(session, headers, logger, resumable_source_manager)
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_before = resume.before if resume is not None else None
    if start_before:
        logger.debug(f"Chameleon: resuming {endpoint} from before={start_before}")

    for rows, next_before in _iter_pages(
        session,
        f"{CHAMELEON_BASE_URL}{config.path}",
        config.data_key,
        headers,
        logger,
        {"limit": config.page_size},
        start_before,
    ):
        if rows:
            yield rows
            if next_before:
                resumable_source_manager.save_state(ChameleonResumeConfig(before=next_before))


def chameleon_source(
    account_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ChameleonResumeConfig],
) -> SourceResponse:
    endpoint_config: ChameleonEndpointConfig = CHAMELEON_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            account_secret=account_secret,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        # Chameleon returns records most-recently-created first.
        sort_mode="desc",
    )
