import dataclasses
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from requests.auth import HTTPBasicAuth
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.campaign_monitor.settings import (
    CAMPAIGN_MONITOR_ENDPOINTS,
    CampaignMonitorEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CAMPAIGN_MONITOR_BASE_URL = "https://api.createsend.com/api/v3.3"
DEFAULT_PAGE_SIZE = 1000  # Campaign Monitor's documented maximum page size.
# Subscriber-state endpoints require a `date`; this fetches the full history (the filter is
# inclusive from the given date onward). Used until server-side incremental is verified live.
FULL_REFRESH_SINCE_DATE = "1900-01-01"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5


class CampaignMonitorRetryableError(Exception):
    pass


@dataclasses.dataclass
class CampaignMonitorResumeConfig:
    # The fan-out list currently being processed. A stable list-ID bookmark (not a positional
    # index) so reordered/added/removed lists between a crash and the retry can't resume us into
    # the wrong list and write rows under the wrong primary key. None for non-fan-out endpoints.
    list_id: str | None = None
    # The fan-out campaign currently being processed (campaign report endpoints). Same stable-ID
    # bookmark rationale as `list_id`. None for endpoints that don't fan out over campaigns.
    campaign_id: str | None = None
    # Next page to fetch (1-based). Always 1 for non-paginated array endpoints.
    page: int = 1


def _auth(api_key: str) -> HTTPBasicAuth:
    # Campaign Monitor uses the API key as the HTTP Basic username; the password is ignored.
    return HTTPBasicAuth(api_key, "x")


def _build_url(path: str, params: dict[str, Any] | None = None) -> str:
    url = f"{CAMPAIGN_MONITOR_BASE_URL}/{path}"
    if params:
        url = f"{url}?{urlencode(params)}"
    return url


def validate_credentials(api_key: str) -> bool:
    """Cheap probe that confirms the API key is genuine via the account-level clients endpoint."""
    url = _build_url("clients.json")
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            url, auth=_auth(api_key), timeout=REQUEST_TIMEOUT_SECONDS
        )
        return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type((CampaignMonitorRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_json(session: requests.Session, api_key: str, url: str, logger: FilteringBoundLogger) -> Any:
    response = session.get(url, auth=_auth(api_key), timeout=REQUEST_TIMEOUT_SECONDS)

    # 1 request/second on most endpoints, so 429s are expected; back off and retry.
    if response.status_code == 429 or response.status_code >= 500:
        raise CampaignMonitorRetryableError(
            f"Campaign Monitor API error (retryable): status={response.status_code}, url={url}"
        )

    if not response.ok:
        logger.error(f"Campaign Monitor API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _list_ids_for_client(
    session: requests.Session, api_key: str, client_id: str, logger: FilteringBoundLogger
) -> list[str]:
    data = _fetch_json(session, api_key, _build_url(f"clients/{client_id}/lists.json"), logger)
    if not isinstance(data, list):
        return []
    return [item["ListID"] for item in data if isinstance(item, dict) and "ListID" in item]


def _campaign_ids_for_client(
    session: requests.Session, api_key: str, client_id: str, logger: FilteringBoundLogger
) -> list[str]:
    # Only sent campaigns have reports, which is exactly what this endpoint returns.
    data = _fetch_json(session, api_key, _build_url(f"clients/{client_id}/campaigns.json"), logger)
    if not isinstance(data, list):
        return []
    return [item["CampaignID"] for item in data if isinstance(item, dict) and "CampaignID" in item]


def _page_params(config: CampaignMonitorEndpointConfig, page: int) -> dict[str, Any]:
    params: dict[str, Any] = {"page": page, "pagesize": DEFAULT_PAGE_SIZE}
    if config.uses_date_filter:
        params["date"] = FULL_REFRESH_SINCE_DATE
    if config.order_field:
        params["orderfield"] = config.order_field
        params["orderdirection"] = "asc"
    return params


def _iter_paginated(
    session: requests.Session,
    api_key: str,
    config: CampaignMonitorEndpointConfig,
    path: str,
    logger: FilteringBoundLogger,
    extra_row_fields: dict[str, Any],
    resumable_source_manager: ResumableSourceManager[CampaignMonitorResumeConfig],
    make_resume: Callable[[int], CampaignMonitorResumeConfig],
    start_page: int,
) -> Iterator[list[dict[str, Any]]]:
    page = start_page
    while True:
        data = _fetch_json(session, api_key, _build_url(path, _page_params(config, page)), logger)
        results = data.get("Results", []) if isinstance(data, dict) else []
        number_of_pages = data.get("NumberOfPages", page) if isinstance(data, dict) else page
        is_last_page = not results or page >= number_of_pages

        if results:
            yield [{**row, **extra_row_fields} for row in results]
            # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last
            # page rather than skipping it — the pipeline's merge dedupes on the primary key.
            if not is_last_page:
                resumable_source_manager.save_state(make_resume(page + 1))

        if is_last_page:
            break
        page += 1


def _iter_fan_out(
    session: requests.Session,
    api_key: str,
    config: CampaignMonitorEndpointConfig,
    parent_ids: list[str],
    path_param: str,
    row_id_field: str,
    make_resume: Callable[[str | None, int], CampaignMonitorResumeConfig],
    resume_parent_id: str | None,
    resume_page: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CampaignMonitorResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    # Resolve the saved parent-ID bookmark to a position. If the parent no longer exists (deleted
    # between runs), fall back to restarting from the first parent — merge dedupes the re-pulled
    # rows on the primary key.
    start_index = 0
    start_page = 1
    if resume_parent_id is not None and resume_parent_id in parent_ids:
        start_index = parent_ids.index(resume_parent_id)
        start_page = resume_page

    for parent_index in range(start_index, len(parent_ids)):
        parent_id = parent_ids[parent_index]
        path = config.path.format(**{path_param: parent_id})
        extra_row_fields = {row_id_field: parent_id}

        if config.paginated:
            # Only the parent we resumed into keeps its saved page; later parents start at page 1.
            page = start_page if parent_index == start_index else 1
            yield from _iter_paginated(
                session,
                api_key,
                config,
                path,
                logger,
                extra_row_fields,
                resumable_source_manager,
                lambda next_page, parent_id=parent_id: make_resume(parent_id, next_page),
                page,
            )
        else:
            # Single-object endpoints (e.g. campaign summary) return one JSON object per parent.
            data = _fetch_json(session, api_key, _build_url(path), logger)
            if isinstance(data, dict) and data:
                yield [{**data, **extra_row_fields}]

        # Advance the bookmark to the next parent so a crash between parents resumes correctly.
        if parent_index + 1 < len(parent_ids):
            resumable_source_manager.save_state(make_resume(parent_ids[parent_index + 1], 1))


def get_rows(
    api_key: str,
    client_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CampaignMonitorResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = CAMPAIGN_MONITOR_ENDPOINTS[endpoint]
    session = make_tracked_session(redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.fan_out_over_lists:
        yield from _iter_fan_out(
            session,
            api_key,
            config,
            _list_ids_for_client(session, api_key, client_id, logger),
            "list_id",
            "ListID",
            lambda parent_id, page: CampaignMonitorResumeConfig(list_id=parent_id, page=page),
            resume.list_id if resume else None,
            resume.page if resume else 1,
            logger,
            resumable_source_manager,
        )
        return

    if config.fan_out_over_campaigns:
        yield from _iter_fan_out(
            session,
            api_key,
            config,
            _campaign_ids_for_client(session, api_key, client_id, logger),
            "campaign_id",
            "CampaignID",
            lambda parent_id, page: CampaignMonitorResumeConfig(campaign_id=parent_id, page=page),
            resume.campaign_id if resume else None,
            resume.page if resume else 1,
            logger,
            resumable_source_manager,
        )
        return

    path = config.path.format(client_id=client_id)

    if config.paginated:
        start_page = resume.page if resume else 1
        yield from _iter_paginated(
            session,
            api_key,
            config,
            path,
            logger,
            {},
            resumable_source_manager,
            lambda next_page: CampaignMonitorResumeConfig(page=next_page),
            start_page,
        )
        return

    # Non-paginated endpoints return a bare JSON array.
    data = _fetch_json(session, api_key, _build_url(path), logger)
    if isinstance(data, list) and data:
        yield data


def campaign_monitor_source(
    api_key: str,
    client_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CampaignMonitorResumeConfig],
) -> SourceResponse:
    config = CAMPAIGN_MONITOR_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            client_id=client_id,
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
        sort_mode="asc",
    )
