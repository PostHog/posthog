import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.klaus.settings import (
    KLAUS_ENDPOINTS,
    KlausEndpointConfig,
)

REQUEST_TIMEOUT = 60
# The public API is aggressively rate limited (on the order of one request per
# minute), so throttled requests are the norm mid-sync, not the exception: honor
# Retry-After and keep the retry budget generous.
MAX_RETRY_ATTEMPTS = 8
MAX_RETRY_WAIT_SECONDS = 300.0
# Klaus was founded in 2018; endpoints with a required fromDate get this floor on
# full refresh / first sync so the window covers all history.
DEFAULT_FROM_DATE = datetime(2015, 1, 1, tzinfo=UTC)
# fromDate's inclusive/exclusive boundary behavior isn't documented, so re-read a
# small window behind the watermark; merge dedupes the overlap on the primary key.
INCREMENTAL_OVERLAP = timedelta(hours=1)

_SUBDOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class KlausRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclasses.dataclass
class KlausResumeConfig:
    # Next page number to request, in the server's own page indexing. None means
    # "start the stream at its first page" — used when the fan-out bookmark advances
    # to a workspace whose first page index isn't known until its response arrives.
    next_page: int | None = None
    # The workspace currently being processed for fan-out endpoints. A stable
    # workspace-ID bookmark (not a positional index) so workspaces added/removed
    # between a crash and the retry can't resume us into the wrong workspace.
    workspace_id: str | None = None


def _normalize_subdomain(subdomain: str) -> str:
    """Reduce whatever the user pasted (bare subdomain, full host, or URL) to the subdomain."""
    value = subdomain.strip().lower()
    value = value.removeprefix("https://").removeprefix("http://")
    value = value.split("/")[0]
    if value.endswith(".zendesk.com"):
        value = value[: -len(".zendesk.com")]
    return value


def get_base_url(subdomain: str) -> str:
    """Build https://{subdomain}.zendesk.com/qa, rejecting anything that could escape the host.

    The strict character allow-list pins the request host under zendesk.com — a value
    with dots or slashes could otherwise splice a different host into the URL and
    receive the bearer token.
    """
    value = _normalize_subdomain(subdomain)
    if not _SUBDOMAIN_RE.match(value):
        raise ValueError(
            "Zendesk QA subdomain must contain only letters, numbers, and hyphens (e.g. 'yourcompany' for yourcompany.zendesk.com)"
        )
    return f"https://{value}.zendesk.com/qa"


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _parse_retry_after(response: requests.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        return None


def _retry_wait(retry_state: RetryCallState) -> float:
    exception = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exception, KlausRetryableError) and exception.retry_after is not None:
        return min(exception.retry_after + 1.0, MAX_RETRY_WAIT_SECONDS)
    return wait_exponential_jitter(initial=10, max=MAX_RETRY_WAIT_SECONDS)(retry_state)


@retry(
    retry=retry_if_exception_type(
        (
            KlausRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=_retry_wait,
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)

    if response.status_code == 429 or response.status_code >= 500:
        raise KlausRetryableError(
            f"Zendesk QA API error (retryable): status={response.status_code}, url={url}",
            retry_after=_parse_retry_after(response),
        )

    # The session never follows redirects (host pinning); a 3xx from a valid
    # account is never expected and almost always means the subdomain is wrong.
    if response.is_redirect:
        raise Exception("Zendesk QA redirected the request, which usually means the configured subdomain is incorrect")

    if not response.ok:
        logger.error(f"Zendesk QA API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None


def _format_datetime(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_params(
    config: KlausEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    from_value: datetime | None = None
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        from_value = _coerce_datetime(db_incremental_field_last_value)
        if from_value is not None:
            from_value -= INCREMENTAL_OVERLAP

    if from_value is None and config.requires_from_date:
        from_value = DEFAULT_FROM_DATE

    if from_value is not None:
        params["fromDate"] = _format_datetime(from_value)

    return params


def _iter_endpoint_pages(
    session: requests.Session,
    headers: dict[str, str],
    url: str,
    params: dict[str, Any],
    config: KlausEndpointConfig,
    resumable_source_manager: ResumableSourceManager[KlausResumeConfig],
    resume_page: int | None,
    workspace_id: str | None,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Page through one endpoint (or one workspace of a fan-out endpoint), yielding row batches.

    The docs don't say whether page numbering starts at 0 or 1, so the first request
    omits `page` and later requests derive the next index from the response's
    pagination echo — correct for either base. proto3 JSON omits zero-valued fields,
    which is why a missing `pagination.page` reads as 0 (a 0-indexed first page).
    """
    next_page: int | None = resume_page
    last_page_echo: int | None = None

    while True:
        request_params = dict(params)
        if config.paginated:
            request_params["pageSize"] = config.page_size
            if next_page is not None:
                request_params["page"] = next_page

        data = _fetch_page(session, url, request_params, headers, logger)
        items = data.get(config.data_selector) or []
        if not items:
            return

        if workspace_id is not None:
            items = [{**item, "workspace_id": workspace_id} for item in items]

        if not config.paginated:
            yield items
            return

        pagination = data.get("pagination") or {}
        current_page = int(pagination.get("page") or 0)
        effective_page_size = int(pagination.get("pageSize") or config.page_size)

        # Fail loudly instead of looping forever if the server stops advancing the
        # page echo (e.g. it silently ignores the page param).
        if last_page_echo is not None and current_page == last_page_echo:
            raise Exception(f"Zendesk QA pagination did not advance (page echo stuck at {current_page}) for {url}")
        last_page_echo = current_page

        has_more = len(items) >= max(effective_page_size, 1)
        yield items

        if not has_more:
            return

        next_page = current_page + 1
        # Save AFTER yielding (and only when more pages remain) so a crash re-yields
        # the last page rather than skipping it — merge dedupes on the primary key.
        resumable_source_manager.save_state(KlausResumeConfig(next_page=next_page, workspace_id=workspace_id))


def _get_workspace_ids(
    session: requests.Session,
    headers: dict[str, str],
    base_url: str,
    logger: FilteringBoundLogger,
) -> list[str]:
    data = _fetch_page(session, f"{base_url}/api/export/workspaces", {}, headers, logger)
    return [str(workspace["id"]) for workspace in data.get("workspaces") or []]


def _iter_fanout_pages(
    session: requests.Session,
    headers: dict[str, str],
    base_url: str,
    params: dict[str, Any],
    config: KlausEndpointConfig,
    resumable_source_manager: ResumableSourceManager[KlausResumeConfig],
    resume: KlausResumeConfig | None,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    workspace_ids = _get_workspace_ids(session, headers, base_url, logger)

    # Resolve the saved workspace bookmark to the slice still to process. If the
    # bookmarked workspace no longer exists, start over from the first one — merge
    # dedupes the re-pulled rows on the primary key.
    remaining = workspace_ids
    resume_page: int | None = None
    if resume is not None and resume.workspace_id is not None and resume.workspace_id in workspace_ids:
        remaining = workspace_ids[workspace_ids.index(resume.workspace_id) :]
        resume_page = resume.next_page
        logger.debug(f"Zendesk QA: resuming {config.name} from workspace={resume.workspace_id}, page={resume_page}")

    for index, workspace_id in enumerate(remaining):
        url = base_url + config.path.format(workspace=workspace_id)
        yield from _iter_endpoint_pages(
            session, headers, url, params, config, resumable_source_manager, resume_page, workspace_id, logger
        )
        resume_page = None  # only the resumed-into workspace starts mid-stream

        # Advance the bookmark so a crash between workspaces resumes at the next one.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(KlausResumeConfig(next_page=None, workspace_id=remaining[index + 1]))


def get_rows(
    subdomain: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KlausResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = KLAUS_ENDPOINTS[endpoint]
    # Re-validate on every sync, not just at source creation: the stored subdomain is
    # user-supplied and must stay pinned under zendesk.com.
    base_url = get_base_url(subdomain)
    headers = _get_headers(api_token)
    # One session reused across every page so urllib3 keeps the connection alive.
    # Redirects stay off as defense-in-depth for host pinning. `capture=False` keeps
    # response bodies out of HTTP sample capture: these endpoints return free-text
    # customer content (review comments, CSAT feedback, conversations) the name-based
    # scrubbers can't reliably remove; requests stay metered and logged.
    session = make_tracked_session(redact_values=(api_token,), allow_redirects=False, capture=False)

    params = _build_params(config, should_use_incremental_field, db_incremental_field_last_value)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.fan_out_over_workspaces:
        yield from _iter_fanout_pages(
            session, headers, base_url, params, config, resumable_source_manager, resume, logger
        )
    else:
        yield from _iter_endpoint_pages(
            session,
            headers,
            base_url + config.path,
            params,
            config,
            resumable_source_manager,
            resume.next_page if resume else None,
            None,
            logger,
        )


def klaus_source(
    subdomain: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KlausResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = KLAUS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            subdomain=subdomain,
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # Zendesk QA doesn't document response ordering and exposes no sort param, so
        # declare desc: the incremental watermark then persists only at successful job
        # end instead of checkpointing per batch against an unverified ordering.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(subdomain: str, api_token: str) -> tuple[bool, str | None]:
    try:
        base_url = get_base_url(subdomain)
    except ValueError as e:
        return False, str(e)

    try:
        # `capture=False` keeps the user listing (names, emails) out of HTTP sample capture.
        response = make_tracked_session(redact_values=(api_token,), allow_redirects=False, capture=False).get(
            f"{base_url}/api/export/users",
            headers=_get_headers(api_token),
            timeout=30,
        )
    except Exception as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid Zendesk QA subdomain or API token"
    if response.status_code == 429:
        # The public API is heavily rate limited; a throttled probe still reached the
        # account's API, so don't block source creation on it.
        return True, None
    if response.is_redirect:
        return (
            False,
            "Zendesk QA redirected the request, which usually means the subdomain is incorrect. "
            "Enter just the subdomain part of yourcompany.zendesk.com",
        )
    return False, f"Zendesk QA returned an unexpected status code: {response.status_code}"
