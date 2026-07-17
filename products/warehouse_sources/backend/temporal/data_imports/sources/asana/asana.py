import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.asana.settings import (
    ASANA_ENDPOINTS,
    PRIMARY_KEY,
    AsanaEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

ASANA_BASE_URL = "https://app.asana.com/api/1.0"
# Asana caps list pages at 100 items.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5


class AsanaRetryableError(Exception):
    pass


@dataclasses.dataclass
class AsanaResumeConfig:
    # Initial request URLs (one per parent for fan-out endpoints) not yet started.
    remaining_urls: list[str]
    # The next page URL to fetch for the in-progress request, or None when finished.
    current_url: Optional[str]


def _get_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _with_query(path: str, params: dict[str, Any]) -> str:
    """Append query params to a relative path that may already carry a `?workspace=` filter."""
    clean = {key: value for key, value in params.items() if value is not None}
    if not clean:
        return f"{ASANA_BASE_URL}{path}"
    separator = "&" if "?" in path else "?"
    return f"{ASANA_BASE_URL}{path}{separator}{urlencode(clean)}"


def _list_params(config: AsanaEndpointConfig) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": PAGE_SIZE}
    if config.opt_fields:
        params["opt_fields"] = ",".join(config.opt_fields)
    return params


@retry(
    retry=retry_if_exception_type((AsanaRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_page(
    url: str, headers: dict[str, str], logger: FilteringBoundLogger, session: requests.Session
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    # Asana rate-limits at 150 req/min (free) / 1500 (paid) and returns 429 with a Retry-After
    # header; exponential backoff is sufficient and avoids parsing the header here.
    if response.status_code == 429 or response.status_code >= 500:
        raise AsanaRetryableError(f"Asana API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Asana API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _iter_items(
    start_url: str, headers: dict[str, str], logger: FilteringBoundLogger, session: requests.Session
) -> Iterator[dict[str, Any]]:
    """Fully paginate a single list request, yielding individual records (used for discovery)."""
    url: Optional[str] = start_url
    while url is not None:
        data = _fetch_page(url, headers, logger, session)
        yield from data.get("data") or []
        next_page = data.get("next_page")
        url = next_page.get("uri") if isinstance(next_page, dict) else None


def _list_workspaces(
    headers: dict[str, str], logger: FilteringBoundLogger, session: requests.Session
) -> list[dict[str, Any]]:
    url = _with_query("/workspaces", {"limit": PAGE_SIZE, "opt_fields": "is_organization"})
    return list(_iter_items(url, headers, logger, session))


def _list_projects(
    headers: dict[str, str], logger: FilteringBoundLogger, session: requests.Session
) -> Iterator[dict[str, Any]]:
    for workspace in _list_workspaces(headers, logger, session):
        gid = workspace["gid"]
        yield from _iter_items(
            _with_query(f"/projects?workspace={gid}", {"limit": PAGE_SIZE}), headers, logger, session
        )


def _build_initial_urls(
    config: AsanaEndpointConfig, headers: dict[str, str], logger: FilteringBoundLogger, session: requests.Session
) -> list[str]:
    """Resolve the set of request URLs for an endpoint, fanning out over parents as needed."""
    params = _list_params(config)

    if config.fan_out == "none":
        return [_with_query(config.path_template, params)]

    if config.fan_out in ("workspace", "organization"):
        urls = []
        for workspace in _list_workspaces(headers, logger, session):
            if config.fan_out == "organization" and not workspace.get("is_organization"):
                # `/organizations/{gid}/teams` is only valid for organization workspaces.
                continue
            urls.append(_with_query(config.path_template.format(gid=workspace["gid"]), params))
        return urls

    if config.fan_out == "project":
        return [
            _with_query(config.path_template.format(gid=project["gid"]), params)
            for project in _list_projects(headers, logger, session)
        ]

    raise ValueError(f"Unknown fan_out mode: {config.fan_out}")


def validate_credentials(access_token: str) -> bool:
    """Confirm the personal access token is valid. /users/me needs no extra scopes."""
    try:
        response = make_tracked_session().get(
            f"{ASANA_BASE_URL}/users/me",
            headers=_get_headers(access_token),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AsanaResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = ASANA_ENDPOINTS[endpoint]
    headers = _get_headers(access_token)
    # One session for the whole run so pagination and fan-out reuse pooled connections.
    session = make_tracked_session()

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        remaining = list(resume_config.remaining_urls)
        current = resume_config.current_url
        logger.debug(f"Asana: resuming {endpoint} from URL: {current}")
    else:
        remaining = _build_initial_urls(config, headers, logger, session)
        current = remaining.pop(0) if remaining else None

    while current is not None:
        data = _fetch_page(current, headers, logger, session)
        items = data.get("data") or []

        next_page = data.get("next_page")
        next_url = next_page.get("uri") if isinstance(next_page, dict) else None

        # Advance: continue the current request's page chain, else move to the next parent URL.
        if next_url:
            new_current: Optional[str] = next_url
            new_remaining = remaining
        elif remaining:
            new_current = remaining[0]
            new_remaining = remaining[1:]
        else:
            new_current = None
            new_remaining = []

        if items:
            yield items

        # Save AFTER yielding (and only while there's more to fetch) so a crash re-yields the
        # last batch — merge dedupes on gid — rather than skipping it.
        if new_current is not None:
            resumable_source_manager.save_state(
                AsanaResumeConfig(remaining_urls=new_remaining, current_url=new_current)
            )

        current = new_current
        remaining = new_remaining


def asana_source(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AsanaResumeConfig],
) -> SourceResponse:
    config = ASANA_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=[PRIMARY_KEY],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
