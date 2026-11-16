import re
import dataclasses
from collections.abc import Callable, Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    make_tracked_session,
    reach_safe_point,
    retry_with_deadline,
)
from products.warehouse_sources.sources.smaily.settings import (
    AB_TEST_STATISTICS,
    ACTION_LOG_ENDPOINTS,
    CAMPAIGN_STATISTICS,
    SEGMENT_RULES,
    SEGMENT_SUBSCRIBERS,
    SEQ_ID_FIELD,
    SMAILY_ENDPOINTS,
    SmailyEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm credentials are genuine: `list.php` takes no params and every API
# user can read it, so one probe validates access to the account.
DEFAULT_PROBE_PATH = "list.php"
# Smaily represents empty datetimes as a zero date instead of null.
ZERO_DATETIME = "0000-00-00 00:00:00"

_SUBDOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class SmailyRetryableError(Exception):
    pass


@dataclasses.dataclass(frozen=False)
class SmailyResumeConfig:
    # Page index within the endpoint (or within the current parent for fan-out endpoints).
    page: int = 0
    # Fan-out endpoints only: parent ids (segments / campaigns) still to fetch, current one first.
    # `None` for top-level endpoints.
    pending_parent_ids: list[str] | None = None
    # Action log endpoints only: the `since_seq_id` of the next page.
    since_seq_id: int | None = None


def normalize_subdomain(subdomain: str) -> str:
    """Reduce whatever the user pasted (bare subdomain, full URL, `x.sendsmaily.net`) to the bare
    subdomain, and reject anything that couldn't be one — the subdomain is interpolated into the
    request host, so it must never smuggle in another domain or a path."""
    value = subdomain.strip().lower()
    value = re.sub(r"^https?://", "", value)
    value = value.split("/", 1)[0]
    value = value.removesuffix(".sendsmaily.net")
    if not _SUBDOMAIN_RE.match(value):
        raise ValueError(f"Invalid Smaily subdomain: '{subdomain}'")
    return value


def _base_url(subdomain: str) -> str:
    return f"https://{normalize_subdomain(subdomain)}.sendsmaily.net/api"


def _make_session(username: str, password: str) -> requests.Session:
    session = make_tracked_session(headers={"Accept": "application/json"}, redact_values=(password,))
    session.auth = (username, password)
    return session


def _safe_point_before_retry_wait(_state: RetryCallState) -> None:
    # Every request runs between pages: the rows before it are yielded, and no caller holds rows
    # while it fetches.
    reach_safe_point()


@retry_with_deadline(
    retry=retry_if_exception_type((SmailyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    before_sleep=_safe_point_before_retry_wait,
    reraise=True,
)
def _fetch(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
    expect_list: bool = False,
) -> Any:
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    # Smaily rate limits at 5 requests/second per IP and returns 429 when exceeded.
    if response.status_code == 429 or response.status_code >= 500:
        raise SmailyRetryableError(f"Smaily API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Smaily API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    try:
        # Smaily serves JSON with a text/html Content-Type header, so parse unconditionally.
        data = response.json()
    except ValueError as e:
        raise SmailyRetryableError(f"Smaily returned a non-JSON payload for {url}") from e

    # Shape validation lives inside the retried function so a malformed payload gets the same
    # backoff treatment as a transport error instead of failing the sync on the first hit.
    if expect_list and (not isinstance(data, list) or not all(isinstance(row, dict) for row in data)):
        raise SmailyRetryableError(f"Smaily returned an unexpected payload for {url}: {type(data).__name__}")

    return data


def _paged_params(config: SmailyEndpointConfig, page: int) -> dict[str, Any]:
    assert config.page_param is not None
    return {**config.extra_params, "limit": config.page_size, config.page_param: page}


def _list_rows(
    session: requests.Session,
    base_url: str,
    config: SmailyEndpointConfig,
    manager: ResumableSourceManager[SmailyResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    url = f"{base_url}/{config.path}"

    if config.page_param is None:
        rows = _fetch(session, url, dict(config.extra_params), logger, expect_list=True)
        if rows:
            yield rows
        return

    resume = manager.load_state() if manager.can_resume() else None
    page = resume.page if resume else 0

    assert config.page_size is not None
    while True:
        rows = _fetch(session, url, _paged_params(config, page), logger, expect_list=True)
        has_next_page = len(rows) >= config.page_size
        if has_next_page:
            manager.save_state(SmailyResumeConfig(page=page + 1))
        if rows:
            yield rows

        if not has_next_page:
            break
        page += 1


def _fetch_all_pages(
    session: requests.Session,
    base_url: str,
    config: SmailyEndpointConfig,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    url = f"{base_url}/{config.path}"
    rows: list[dict[str, Any]] = []
    page = 0
    while True:
        page_rows = _fetch(session, url, _paged_params(config, page), logger, expect_list=True)
        rows.extend(page_rows)
        assert config.page_size is not None
        if len(page_rows) < config.page_size:
            return rows
        page += 1


def _normalize_subscriber(row: dict[str, Any], segment_id: str) -> dict[str, Any]:
    # Zero dates become nulls so the columns can be parsed as timestamps downstream. `segment_id`
    # is injected for the composite primary key (subscriber rows don't carry their segment).
    normalized: dict[str, Any] = {key: (None if value == ZERO_DATETIME else value) for key, value in row.items()}
    normalized["segment_id"] = segment_id
    return normalized


def _segment_subscriber_rows(
    session: requests.Session,
    base_url: str,
    manager: ResumableSourceManager[SmailyResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = SMAILY_ENDPOINTS[SEGMENT_SUBSCRIBERS]
    url = f"{base_url}/{config.path}"

    resume = manager.load_state() if manager.can_resume() else None
    if resume and resume.pending_parent_ids is not None:
        pending = list(resume.pending_parent_ids)
        page = resume.page
    else:
        segments = _fetch(session, f"{base_url}/list.php", {}, logger, expect_list=True)
        # Sort by id so the resume queue stays deterministic (list.php orders by mutable name).
        pending = sorted(str(segment["id"]) for segment in segments)
        page = 0

    assert config.page_size is not None
    while pending:
        segment_id = pending[0]

        while True:
            params = {"list": segment_id, **_paged_params(config, page)}
            rows = _fetch(session, url, params, logger, expect_list=True)
            normalized = [_normalize_subscriber(row, segment_id) for row in rows]
            has_next_page = len(rows) >= config.page_size
            if has_next_page:
                manager.save_state(SmailyResumeConfig(page=page + 1, pending_parent_ids=pending))
            else:
                manager.save_state(SmailyResumeConfig(page=0, pending_parent_ids=pending[1:]))
            if normalized:
                yield normalized
            else:
                manager.safe_point()

            if not has_next_page:
                break
            page += 1

        pending = pending[1:]
        page = 0


def _per_parent_rows(
    manager: ResumableSourceManager[SmailyResumeConfig],
    list_parent_ids: Callable[[], list[str]],
    rows_for_parent: Callable[[str], list[dict[str, Any]]],
) -> Iterator[list[dict[str, Any]]]:
    resume = manager.load_state() if manager.can_resume() else None
    if resume and resume.pending_parent_ids is not None:
        pending = list(resume.pending_parent_ids)
    else:
        pending = list_parent_ids()

    # The rows of one parent are yielded at once: a local batch would hold rows across many
    # requests, where the run can neither stop nor commit its cursor.
    while pending:
        rows = rows_for_parent(pending[0])
        pending = pending[1:]
        manager.save_state(SmailyResumeConfig(page=0, pending_parent_ids=pending))
        if rows:
            yield rows
        else:
            manager.safe_point()


def _campaign_statistics_rows(
    session: requests.Session,
    base_url: str,
    manager: ResumableSourceManager[SmailyResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    url = f"{base_url}/{SMAILY_ENDPOINTS[CAMPAIGN_STATISTICS].path}"

    def list_campaign_ids() -> list[str]:
        campaigns = _fetch_all_pages(session, base_url, SMAILY_ENDPOINTS["campaigns"], logger)
        return [str(campaign["id"]) for campaign in campaigns]

    def stats_for_campaign(campaign_id: str) -> list[dict[str, Any]]:
        stats = _fetch(session, url, {"id": campaign_id}, logger)
        if isinstance(stats, dict) and stats:
            return [stats]
        # Keep one row per campaign even when the stats payload is unusable (e.g. an empty
        # list for a never-sent campaign) so the table doesn't silently omit campaigns;
        # the stats columns stay null. Match the numeric id type of regular stats rows.
        logger.warning(f"Smaily: campaign {campaign_id} statistics had an unexpected payload shape")
        return [{"id": int(campaign_id) if campaign_id.isdigit() else campaign_id}]

    yield from _per_parent_rows(manager, list_campaign_ids, stats_for_campaign)


def _segment_rules_rows(
    session: requests.Session,
    base_url: str,
    manager: ResumableSourceManager[SmailyResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    url = f"{base_url}/{SMAILY_ENDPOINTS[SEGMENT_RULES].path}"

    def list_segment_ids() -> list[str]:
        segments = _fetch(session, url, {}, logger, expect_list=True)
        return sorted(str(segment["id"]) for segment in segments)

    def rules_for_segment(segment_id: str) -> list[dict[str, Any]]:
        segment = _fetch(session, url, {"id": segment_id}, logger)
        if isinstance(segment, dict) and segment:
            return [segment]
        logger.warning(f"Smaily: segment {segment_id} rules had an unexpected payload shape")
        return []

    yield from _per_parent_rows(manager, list_segment_ids, rules_for_segment)


def _ab_test_statistics_rows(
    session: requests.Session,
    base_url: str,
    manager: ResumableSourceManager[SmailyResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    url = f"{base_url}/{SMAILY_ENDPOINTS[AB_TEST_STATISTICS].path}"

    def list_ab_test_ids() -> list[str]:
        ab_tests = _fetch_all_pages(session, base_url, SMAILY_ENDPOINTS["ab_tests"], logger)
        return [str(ab_test["id"]) for ab_test in ab_tests]

    def stats_for_ab_test(ab_test_id: str) -> list[dict[str, Any]]:
        # Without `detailed=1` the response is one summary object per section, with no
        # per-recipient `addresses` list.
        sections = _fetch(session, url, {"id": ab_test_id}, logger)
        if isinstance(sections, dict):
            sections = [sections] if sections else []
        if not isinstance(sections, list) or not all(isinstance(section, dict) for section in sections):
            logger.warning(f"Smaily: A/B test {ab_test_id} statistics had an unexpected payload shape")
            return []
        typed_id: int | str = int(ab_test_id) if ab_test_id.isdigit() else ab_test_id
        return [{**section, "ab_test_id": typed_id, "section_index": index} for index, section in enumerate(sections)]

    yield from _per_parent_rows(manager, list_ab_test_ids, stats_for_ab_test)


def _action_log_rows(
    session: requests.Session,
    base_url: str,
    config: SmailyEndpointConfig,
    manager: ResumableSourceManager[SmailyResumeConfig],
    logger: FilteringBoundLogger,
    since_seq_id: int,
) -> Iterator[list[dict[str, Any]]]:
    """Walk an action log by `since_seq_id`, which returns the actions after that sequence number
    in ascending `seq_id` order. The API rejects `offset` together with `since_seq_id`, so each page
    starts after the last `seq_id` of the page before."""
    url = f"{base_url}/{config.path}"

    resume = manager.load_state() if manager.can_resume() else None
    if resume and resume.since_seq_id is not None:
        since_seq_id = resume.since_seq_id

    assert config.page_size is not None
    while True:
        params = {"since_seq_id": since_seq_id, "limit": config.page_size}
        rows = _fetch(session, url, params, logger, expect_list=True)
        if not rows:
            return

        last_seq_id = max(int(row[SEQ_ID_FIELD]) for row in rows)
        if last_seq_id <= since_seq_id:
            raise ValueError(f"Smaily {config.name}: since_seq_id={since_seq_id} returned no newer actions")

        # Checkpoint the final page too: an append resume must not fetch its rows again.
        manager.save_state(SmailyResumeConfig(since_seq_id=last_seq_id))
        yield rows

        if len(rows) < config.page_size:
            return
        since_seq_id = last_seq_id


def _initial_since_seq_id(should_use_incremental_field: bool, db_incremental_field_last_value: Any) -> int:
    # 0 reads the log from its first retained action.
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        return int(db_incremental_field_last_value)
    return 0


def get_rows(
    subdomain: str,
    username: str,
    password: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SmailyResumeConfig],
    since_seq_id: int = 0,
) -> Iterator[list[dict[str, Any]]]:
    config = SMAILY_ENDPOINTS[endpoint]
    session = _make_session(username, password)
    base_url = _base_url(subdomain)

    if endpoint == SEGMENT_SUBSCRIBERS:
        yield from _segment_subscriber_rows(session, base_url, resumable_source_manager, logger)
    elif endpoint == CAMPAIGN_STATISTICS:
        yield from _campaign_statistics_rows(session, base_url, resumable_source_manager, logger)
    elif endpoint == SEGMENT_RULES:
        yield from _segment_rules_rows(session, base_url, resumable_source_manager, logger)
    elif endpoint == AB_TEST_STATISTICS:
        yield from _ab_test_statistics_rows(session, base_url, resumable_source_manager, logger)
    elif endpoint in ACTION_LOG_ENDPOINTS:
        yield from _action_log_rows(session, base_url, config, resumable_source_manager, logger, since_seq_id)
    else:
        yield from _list_rows(session, base_url, config, resumable_source_manager, logger)


def smaily_source(
    subdomain: str,
    username: str,
    password: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SmailyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = SMAILY_ENDPOINTS[endpoint]
    is_action_log = endpoint in ACTION_LOG_ENDPOINTS
    since_seq_id = _initial_since_seq_id(should_use_incremental_field, db_incremental_field_last_value)

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            subdomain=subdomain,
            username=username,
            password=password,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            since_seq_id=since_seq_id,
        ),
        primary_keys=config.primary_keys,
        # The action logs return rows in ascending `seq_id` order when paged by `since_seq_id`.
        sort_mode="asc" if is_action_log else None,
        partition_count=None if config.partition_key else 1,
        partition_size=None if config.partition_key else 1,
        partition_mode="datetime" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
    )


def check_access(subdomain: str, username: str, password: str) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the credentials.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem or malformed subdomain, other HTTP status otherwise.
    """
    try:
        base_url = _base_url(subdomain)
    except ValueError as e:
        return 0, str(e)

    session = _make_session(username, password)
    try:
        response = session.get(f"{base_url}/{DEFAULT_PROBE_PATH}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Smaily: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Smaily returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(subdomain: str, username: str, password: str) -> tuple[bool, str | None]:
    status, message = check_access(subdomain, username, password)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Smaily credentials. Check your subdomain, API username and password."
    return False, message or "Could not validate Smaily credentials"
