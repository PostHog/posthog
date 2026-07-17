import dataclasses
from collections.abc import Iterator
from typing import Any

import requests
import structlog
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.less_annoying_crm.settings import (
    LESS_ANNOYING_CRM_ENDPOINTS,
    WIDE_WINDOW_END,
    WIDE_WINDOW_START,
    LessAnnoyingCRMEndpointConfig,
)

# Single flat RPC endpoint — every call is a POST here with a {"Function", "Parameters"} body.
LESS_ANNOYING_CRM_BASE_URL = "https://api.lessannoyingcrm.com/v2/"

# The API caps MaxNumberOfResults at 10,000. We page at 500 (the API default) so each yielded page
# stays small; the pipeline batches across pages so a smaller page size costs only extra requests.
PAGE_SIZE = 500

REQUEST_TIMEOUT_SECONDS = 60

logger = structlog.get_logger(__name__)


class LessAnnoyingCRMRetryableError(Exception):
    """Raised for transient failures (429 / 5xx / connection) that are worth retrying."""


class LessAnnoyingCRMError(Exception):
    """Raised for terminal API errors. Carries the API's ErrorDescription so credential/permission
    failures surface a friendly, matchable message (LACRM returns these as HTTP 400 with a JSON body,
    not 401/403)."""


@dataclasses.dataclass
class LessAnnoyingCRMResumeConfig:
    # Next page number to request. Full refresh only, so page number is the entire cursor: on resume
    # we re-request the last saved page (merge dedupes on the primary key).
    page: int = 1


def _get_headers(api_key: str) -> dict[str, str]:
    # LACRM sends the raw API key as the Authorization header value — no Bearer prefix, no OAuth.
    return {"Authorization": api_key, "Content-Type": "application/json"}


def _extract_records(data: Any, result_path: list[str]) -> list[dict[str, Any]]:
    """Walk ``result_path`` to the record collection and normalize it to a list of dicts.

    LACRM returns list endpoints under ``Results`` (or a bare array for users/teams). GetTasks nests
    its results as an object keyed by id, so a dict at the leaf is expanded to its values."""
    node = data
    for key in result_path:
        if not isinstance(node, dict):
            return []
        node = node.get(key)
    if isinstance(node, dict):
        return [v for v in node.values() if isinstance(v, dict)]
    if isinstance(node, list):
        return [item for item in node if isinstance(item, dict)]
    return []


def _is_error_body(data: Any) -> bool:
    return isinstance(data, dict) and ("ErrorCode" in data or "ErrorDescription" in data)


@retry(
    retry=retry_if_exception_type(
        (
            LessAnnoyingCRMRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _call_function(
    session: requests.Session,
    api_key: str,
    function: str,
    parameters: dict[str, Any],
    logger: FilteringBoundLogger,
) -> Any:
    response = session.post(
        LESS_ANNOYING_CRM_BASE_URL,
        headers=_get_headers(api_key),
        json={"Function": function, "Parameters": parameters},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise LessAnnoyingCRMRetryableError(
            f"Less Annoying CRM API error (retryable): status={response.status_code}, function={function}"
        )

    # Errors (including invalid credentials) come back as HTTP 400 with a JSON body carrying
    # ErrorCode / ErrorDescription. Surface the description so it can be matched as non-retryable.
    try:
        data = response.json()
    except ValueError:
        data = None

    if not response.ok or _is_error_body(data):
        description = data.get("ErrorDescription") if isinstance(data, dict) else None
        message = description or f"HTTP {response.status_code}"
        logger.error(f"Less Annoying CRM API error: function={function}, status={response.status_code}, body={message}")
        raise LessAnnoyingCRMError(f"Less Annoying CRM API error for {function}: {message}")

    return data


def _build_parameters(config: LessAnnoyingCRMEndpointConfig, page: int) -> dict[str, Any]:
    parameters: dict[str, Any] = {}
    if config.paginated:
        parameters["Page"] = page
        parameters["MaxNumberOfResults"] = PAGE_SIZE
    if config.date_window_params:
        start_param, end_param = config.date_window_params
        parameters[start_param] = WIDE_WINDOW_START
        parameters[end_param] = WIDE_WINDOW_END
    if config.sort_by:
        parameters["SortBy"] = config.sort_by
    if config.sort_direction:
        parameters["SortDirection"] = config.sort_direction
    return parameters


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is genuine with the cheapest possible probe.

    ``GetUser`` takes no parameters and always returns the authenticated user, so it validates the
    key without touching any specific resource's read permissions."""
    try:
        session = make_tracked_session(redact_values=(api_key,))
        data = _call_function(session, api_key, "GetUser", {}, logger=logger)
        return not _is_error_body(data)
    except Exception:
        return False


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LessAnnoyingCRMResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = LESS_ANNOYING_CRM_ENDPOINTS[endpoint]
    # Redact the key so it can never land in tracked HTTP request/response samples.
    session = make_tracked_session(redact_values=(api_key,))

    # Non-paginated reference tables (users, teams) are a single call.
    if not config.paginated:
        data = _call_function(session, api_key, config.function, _build_parameters(config, page=1), logger)
        records = _extract_records(data, config.result_path)
        if records:
            yield records
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume else 1

    while True:
        data = _call_function(session, api_key, config.function, _build_parameters(config, page), logger)
        records = _extract_records(data, config.result_path)

        if records:
            yield records

        # LACRM signals more pages via HasMoreResults. Fall back to a short-page heuristic if the flag
        # is absent so we never loop forever on an endpoint that omits it.
        has_more = data.get("HasMoreResults") if isinstance(data, dict) else None
        if has_more is None:
            has_more = len(records) >= PAGE_SIZE
        if not has_more or not records:
            break

        page += 1
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it.
        resumable_source_manager.save_state(LessAnnoyingCRMResumeConfig(page=page))


def less_annoying_crm_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LessAnnoyingCRMResumeConfig],
) -> SourceResponse:
    config = LESS_ANNOYING_CRM_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
