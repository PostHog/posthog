from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.settings import OPTIMIZELY_ENDPOINTS

OPTIMIZELY_API_HOST = "api.optimizely.com"
OPTIMIZELY_BASE_URL = f"https://{OPTIMIZELY_API_HOST}/v2"
# Optimizely list pages cap at 100 items.
PAGE_SIZE = 100
# Safety bound per page chain — experiment config entities never come close.
MAX_PAGES = 500
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5


class OptimizelyRetryableError(Exception):
    pass


def _is_optimizely_url(url: str) -> bool:
    """Return True only for https URLs on the Optimizely API host."""
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.netloc == OPTIMIZELY_API_HOST


def _get_session(api_token: str) -> requests.Session:
    return make_tracked_session(headers={"Authorization": f"Bearer {api_token}"}, redact_values=(api_token,))


def validate_credentials(api_token: str) -> bool:
    """Confirm the personal access token is valid with a cheap projects probe."""
    try:
        response = _get_session(api_token).get(
            f"{OPTIMIZELY_BASE_URL}/projects?{urlencode({'per_page': 1})}",
            timeout=10,
        )
        return response.status_code != 401
    except Exception:
        return False


def _iterate_pages(
    session: requests.Session,
    path: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Page through one list endpoint via RFC 5988 Link headers."""

    @retry(
        retry=retry_if_exception_type((OptimizelyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch(page_url: str) -> requests.Response:
        response = session.get(page_url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise OptimizelyRetryableError(
                f"Optimizely API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"Optimizely API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response

    url = f"{OPTIMIZELY_BASE_URL}{path}?{urlencode({**params, 'per_page': PAGE_SIZE})}"
    for _page_index in range(MAX_PAGES):
        response = fetch(url)
        data = response.json()
        items = data if isinstance(data, list) else []

        if items:
            yield items

        next_url = response.links.get("next", {}).get("url")
        if not next_url:
            return
        # Only follow pagination URLs that stay on the Optimizely API host, so a
        # tampered or compromised API response can't redirect our authenticated
        # Bearer request to an internal address (SSRF) or external host (token theft).
        if not _is_optimizely_url(next_url):
            logger.error(f"Optimizely: unexpected next_url host, stopping pagination (url={next_url!r})")
            return
        url = next_url

    logger.error(f"Optimizely: page cap ({MAX_PAGES}) reached for {path} with params {params}; output may be truncated")


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = OPTIMIZELY_ENDPOINTS[endpoint]
    session = _get_session(api_token)

    if not config.project_scoped:
        yield from _iterate_pages(session, config.path, {}, logger)
        return

    # Project-scoped endpoints fan out over every project. A project without
    # access to the feature (e.g. campaigns on a non-Web project) can 400/403 —
    # log and continue rather than failing the whole stream.
    project_ids: list[int] = []
    for page in _iterate_pages(session, "/projects", {}, logger):
        project_ids.extend(item["id"] for item in page if item.get("id") is not None)

    for project_id in project_ids:
        try:
            yield from _iterate_pages(session, config.path, {"project_id": project_id}, logger)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status in (400, 403, 404):
                logger.warning(f"Optimizely: skipping {endpoint} for project {project_id} (status={status})")
                continue
            raise


def optimizely_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = OPTIMIZELY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )
