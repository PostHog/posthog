from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.codacy.settings import CODACY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

CODACY_BASE_URL = "https://api.codacy.com/api/v3"
# Documented maximum page size for v3 list endpoints.
DEFAULT_PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60


class CodacyRetryableError(Exception):
    pass


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "api-token": api_token,
        "Accept": "application/json",
    }


@retry(
    retry=retry_if_exception_type(
        (
            CodacyRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    method: str,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    if method == "POST":
        # searchRepositoryIssues takes its filters in the body; an empty filter returns every
        # current issue. Pagination params stay in the query string.
        response = session.post(url, headers=headers, json={}, timeout=REQUEST_TIMEOUT_SECONDS)
    else:
        response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    # Codacy Cloud rate-limits at 2500 requests per 5 minutes per IP, surfacing as 429/503/504.
    if response.status_code == 429 or response.status_code >= 500:
        raise CodacyRetryableError(f"Codacy API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # 404 during a repository fan-out is expected (repository removed from Codacy mid-sync)
        # and handled by the caller; anything else is a hard failure.
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Codacy API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _build_url(path: str, params: dict[str, Any]) -> str:
    return f"{CODACY_BASE_URL}{path}?{urlencode(params)}"


def _paginate(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    path: str,
    method: str = "GET",
    extra_params: Optional[dict[str, str]] = None,
    max_pages: Optional[int] = None,
) -> Iterator[list[dict[str, Any]]]:
    """Yield one list of items per page, following Codacy's cursor pagination.

    Each response carries `pagination.cursor` pointing at the next batch; the final page
    omits the cursor (verified against the live API).
    """
    cursor: Optional[str] = None
    page_count = 0

    while True:
        params: dict[str, Any] = {"limit": DEFAULT_PAGE_SIZE, **(extra_params or {})}
        if cursor:
            params["cursor"] = cursor

        data = _fetch_page(session, method, _build_url(path, params), headers, logger)
        items = data.get("data", [])
        if items:
            yield items

        cursor = (data.get("pagination") or {}).get("cursor")
        if not cursor or not items:
            break

        page_count += 1
        if max_pages is not None and page_count >= max_pages:
            logger.warning(f"Codacy: page cap reached for path={path}, max_pages={max_pages}; results truncated")
            break


def _normalize_item(endpoint: str, item: dict[str, Any], repository: Optional[str] = None) -> dict[str, Any]:
    """Lift the envelope's entity object to the top level and stamp the repository name onto
    fan-out rows, so primary keys are plain top-level columns."""
    if endpoint == "repositories":
        nested = item.pop("repository", None) or {}
        return {**nested, **item}
    if endpoint == "pull_requests":
        nested = item.pop("pullRequest", None) or {}
        return {"repository": repository, **nested, **item}
    if endpoint == "commits":
        nested = item.pop("commit", None) or {}
        return {"repository": repository, **nested, **item}
    if repository is not None:
        return {"repository": repository, **item}
    return item


def _iter_repository_names(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    provider: str,
    organization: str,
) -> Iterator[str]:
    path = f"/organizations/{provider}/{organization}/repositories"
    for page in _paginate(session, headers, logger, path):
        for repository in page:
            name = repository.get("name")
            if name:
                yield name


def get_rows(
    api_token: str,
    provider: str,
    organization: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    endpoint_config = CODACY_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)
    # One session reused across every page (and repository) so urllib3 keeps the connection
    # alive instead of re-handshaking per request.
    session = make_tracked_session()

    if not endpoint_config.fan_out_per_repository:
        path = endpoint_config.path.format(provider=provider, organization=organization)
        for page in _paginate(session, headers, logger, path, endpoint_config.method, endpoint_config.extra_params):
            yield [_normalize_item(endpoint, item) for item in page]
        return

    for repository in _iter_repository_names(session, headers, logger, provider, organization):
        path = endpoint_config.path.format(provider=provider, organization=organization, repository=repository)
        try:
            for page in _paginate(
                session,
                headers,
                logger,
                path,
                endpoint_config.method,
                endpoint_config.extra_params,
                max_pages=endpoint_config.max_pages_per_repository,
            ):
                yield [_normalize_item(endpoint, item, repository=repository) for item in page]
        except requests.HTTPError as exc:
            # A repository removed from Codacy between enumeration and this fetch 404s; skip it
            # rather than failing the whole sync. Anything else is re-raised.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Codacy: repository {repository} not found while fetching {endpoint}, skipping")
            else:
                raise


def codacy_source(
    api_token: str,
    provider: str,
    organization: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    endpoint_config = CODACY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            provider=provider,
            organization=organization,
            endpoint=endpoint,
            logger=logger,
        ),
        primary_keys=endpoint_config.primary_keys,
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def validate_credentials(api_token: str) -> bool:
    url = _build_url("/user/organizations", {"limit": 1})
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_token), timeout=10)
        return response.status_code == 200
    except Exception:
        return False
