from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.codacy.settings import (
    CODACY_ENDPOINTS,
    METRICS_LOOKBACK_DAYS,
    METRICS_PERIOD,
    CodacyEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

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
    body: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if method == "POST":
        # searchRepositoryIssues takes its filters in the body; an empty filter returns every
        # current issue. The metrics time series requires a populated body. Pagination params
        # stay in the query string either way.
        response = session.post(url, headers=headers, json=body or {}, timeout=REQUEST_TIMEOUT_SECONDS)
    else:
        response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    # Codacy Cloud rate-limits at 2500 requests per 5 minutes per IP, surfacing as 429/503/504.
    if response.status_code == 429 or response.status_code >= 500:
        raise CodacyRetryableError(f"Codacy API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # 404 during a fan-out is expected (the parent was removed from Codacy mid-sync) and
        # handled by the caller; anything else is a hard failure.
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Codacy API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _build_url(path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{CODACY_BASE_URL}{path}"
    return f"{CODACY_BASE_URL}{path}?{urlencode(params)}"


def _paginate(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    path: str,
    method: str = "GET",
    extra_params: Optional[dict[str, str]] = None,
    max_pages: Optional[int] = None,
    body: Optional[dict[str, Any]] = None,
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

        data = _fetch_page(session, method, _build_url(path, params), headers, logger, body)
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


def _issues_overview_rows(data: Any) -> list[dict[str, Any]]:
    """Unnest the overview's parallel count arrays into one row per breakdown value.

    The endpoint answers with a single object holding one count array per dimension (category,
    severity level, language, author, tag, pattern). Kept nested, the table could not be grouped
    or filtered by dimension, which is the only thing the counts are useful for.
    """
    counts = (data or {}).get("counts") or {}
    rows: list[dict[str, Any]] = []
    for dimension, entries in counts.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            # The `patterns` breakdown is keyed by pattern id with the title alongside; every
            # other dimension carries a bare name.
            name = entry.get("name") or entry.get("id")
            if name is None:
                continue
            rows.append(
                {
                    "dimension": dimension,
                    "name": name,
                    "total": entry.get("total"),
                    "title": entry.get("title"),
                }
            )
    return rows


def _expand_single_payload(endpoint: str, data: Any) -> list[dict[str, Any]]:
    """Turn the `data` value of a one-shot response into the rows of the table."""
    if endpoint == "issues_overview":
        return _issues_overview_rows(data)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def _iter_endpoint_pages(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    endpoint_config: CodacyEndpointConfig,
    path: str,
    max_pages: Optional[int] = None,
    body: Optional[dict[str, Any]] = None,
) -> Iterator[list[dict[str, Any]]]:
    """Yield raw item lists for one endpoint call, whichever response style it uses."""
    if endpoint_config.paginated:
        yield from _paginate(
            session,
            headers,
            logger,
            path,
            endpoint_config.method,
            endpoint_config.extra_params,
            max_pages=max_pages,
            body=body,
        )
        return

    url = _build_url(path, dict(endpoint_config.extra_params))
    data = _fetch_page(session, endpoint_config.method, url, headers, logger, body).get("data")
    items = _expand_single_payload(endpoint_config.name, data)
    if items:
        yield items


def _normalize_item(endpoint: str, item: dict[str, Any], stamp: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Lift the envelope's entity object to the top level and stamp the fan-out parent's
    identifiers onto the row, so primary keys are plain top-level columns."""
    stamp = stamp or {}
    if endpoint == "repositories":
        nested = item.pop("repository", None) or {}
        return {**nested, **item}
    if endpoint == "pull_requests":
        nested = item.pop("pullRequest", None) or {}
        return {**stamp, **nested, **item}
    if endpoint == "commits":
        nested = item.pop("commit", None) or {}
        return {**stamp, **nested, **item}
    if endpoint == "commit_delta_issues":
        nested = item.pop("commitIssue", None) or {}
        return {**stamp, **nested, **item}
    if endpoint == "category_overviews":
        category = item.pop("category", None) or {}
        return {
            **stamp,
            "categoryName": category.get("name"),
            "categoryType": category.get("categoryType"),
            "categoryDescription": category.get("description"),
            **item,
        }
    if endpoint == "pull_request_coverage":
        nested = item.pop("pullRequest", None) or {}
        coverage = item.pop("coverage", None) or {}
        return {**stamp, **nested, **coverage, **item}
    if endpoint == "metrics_timerange":
        group = item.pop("group", None) or {}
        return {
            **stamp,
            "organization": group.get("organization"),
            # A null key column never matches on merge, so an ungrouped value would be
            # re-inserted on every sync; key it on an empty repository name instead.
            "repository": group.get("repository") or "",
            "dimensions": group.get("dimensions"),
            **item,
        }
    return {**stamp, **item}


def _skip_missing_parent(
    exc: requests.HTTPError, logger: FilteringBoundLogger, endpoint: str, description: str
) -> None:
    """Swallow a 404 raised while fetching a fan-out parent's children; re-raise anything else."""
    if exc.response is not None and exc.response.status_code == 404:
        logger.warning(f"Codacy: {description} not found while fetching {endpoint}, skipping")
        return
    raise exc


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


def _iter_tool_uuids(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> Iterator[str]:
    for page in _paginate(session, headers, logger, "/tools"):
        for tool in page:
            uuid = tool.get("uuid")
            if uuid:
                yield uuid


def _collect_commit_shas(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    provider: str,
    organization: str,
    repository: str,
    limit: int,
) -> list[str]:
    path = f"/analysis/organizations/{provider}/{organization}/repositories/{repository}/commits"
    shas: list[str] = []
    for page in _paginate(session, headers, logger, path):
        for entry in page:
            sha = (entry.get("commit") or {}).get("sha")
            if sha:
                shas.append(sha)
            if len(shas) >= limit:
                logger.warning(
                    f"Codacy: commit cap reached for repository={repository}, max_commits={limit}; "
                    "older commits are not expanded"
                )
                return shas
    return shas


def _collect_pull_request_numbers(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    provider: str,
    organization: str,
    repository: str,
    limit: int,
) -> list[int]:
    # Analysed pull requests only: coverage is derived from the analysis, so the unanalysed ones
    # the `pull_requests` table deliberately includes would only answer 404 here.
    path = f"/analysis/organizations/{provider}/{organization}/repositories/{repository}/pull-requests"
    numbers: list[int] = []
    for page in _paginate(session, headers, logger, path):
        for entry in page:
            number = (entry.get("pullRequest") or {}).get("number")
            if number is None:
                continue
            numbers.append(number)
            if len(numbers) >= limit:
                logger.warning(
                    f"Codacy: pull request cap reached for repository={repository}, max_pull_requests={limit}; "
                    "older pull requests are not expanded"
                )
                return numbers
    return numbers


def _list_ready_metrics(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    provider: str,
    organization: str,
) -> list[str]:
    path = f"/organizations/{provider}/{organization}/metrics/ready"
    try:
        data = _fetch_page(session, "GET", _build_url(path, {}), headers, logger)
    except requests.HTTPError as exc:
        # Metrics are an opt-in Codacy feature; an organization without it answers 403/404 here.
        # Sync an empty table rather than failing the schema.
        if exc.response is not None and exc.response.status_code in (403, 404):
            logger.warning(f"Codacy: no metrics available for organization {organization}, skipping")
            return []
        raise
    return (data.get("data") or {}).get("readyMetrics") or []


def _metrics_request_body() -> dict[str, Any]:
    today = datetime.now(UTC).date()
    return {
        "filter": {"entityFilter": {}},
        "groupBy": {"groupBy": ["repository"]},
        "from": (today - timedelta(days=METRICS_LOOKBACK_DAYS)).isoformat(),
        "to": today.isoformat(),
        "period": METRICS_PERIOD,
    }


def _fan_out_over_repositories(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    provider: str,
    organization: str,
    endpoint_config: CodacyEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    endpoint = endpoint_config.name
    for repository in _iter_repository_names(session, headers, logger, provider, organization):
        path = endpoint_config.path.format(provider=provider, organization=organization, repository=repository)
        try:
            for page in _iter_endpoint_pages(
                session,
                headers,
                logger,
                endpoint_config,
                path,
                max_pages=endpoint_config.max_pages_per_parent,
            ):
                yield [_normalize_item(endpoint, item, {"repository": repository}) for item in page]
        except requests.HTTPError as exc:
            _skip_missing_parent(exc, logger, endpoint, f"repository {repository}")


def _fan_out_over_commits(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    provider: str,
    organization: str,
    endpoint_config: CodacyEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    endpoint = endpoint_config.name
    for repository in _iter_repository_names(session, headers, logger, provider, organization):
        try:
            shas = _collect_commit_shas(
                session,
                headers,
                logger,
                provider,
                organization,
                repository,
                endpoint_config.max_commits_per_repository,
            )
        except requests.HTTPError as exc:
            _skip_missing_parent(exc, logger, endpoint, f"repository {repository}")
            continue

        for sha in shas:
            path = endpoint_config.path.format(
                provider=provider, organization=organization, repository=repository, commit=sha
            )
            try:
                for page in _paginate(
                    session,
                    headers,
                    logger,
                    path,
                    endpoint_config.method,
                    endpoint_config.extra_params,
                    max_pages=endpoint_config.max_pages_per_parent,
                ):
                    yield [
                        _normalize_item(endpoint, item, {"repository": repository, "commitSha": sha}) for item in page
                    ]
            except requests.HTTPError as exc:
                _skip_missing_parent(exc, logger, endpoint, f"commit {sha} of repository {repository}")


def _fan_out_over_pull_requests(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    provider: str,
    organization: str,
    endpoint_config: CodacyEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    endpoint = endpoint_config.name
    for repository in _iter_repository_names(session, headers, logger, provider, organization):
        try:
            numbers = _collect_pull_request_numbers(
                session,
                headers,
                logger,
                provider,
                organization,
                repository,
                endpoint_config.max_pull_requests_per_repository,
            )
        except requests.HTTPError as exc:
            _skip_missing_parent(exc, logger, endpoint, f"repository {repository}")
            continue

        for number in numbers:
            path = endpoint_config.path.format(
                provider=provider, organization=organization, repository=repository, pull_request=number
            )
            try:
                for page in _iter_endpoint_pages(
                    session,
                    headers,
                    logger,
                    endpoint_config,
                    path,
                    max_pages=endpoint_config.max_pages_per_parent,
                ):
                    yield [
                        _normalize_item(endpoint, item, {"repository": repository, "pullRequestNumber": number})
                        for item in page
                    ]
            except requests.HTTPError as exc:
                _skip_missing_parent(exc, logger, endpoint, f"pull request {number} of repository {repository}")


def _fan_out_over_tools(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    endpoint_config: CodacyEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    endpoint = endpoint_config.name
    for tool_uuid in _iter_tool_uuids(session, headers, logger):
        path = endpoint_config.path.format(tool_uuid=tool_uuid)
        try:
            for page in _paginate(
                session,
                headers,
                logger,
                path,
                endpoint_config.method,
                endpoint_config.extra_params,
                max_pages=endpoint_config.max_pages_per_parent,
            ):
                yield [_normalize_item(endpoint, item, {"toolUuid": tool_uuid}) for item in page]
        except requests.HTTPError as exc:
            _skip_missing_parent(exc, logger, endpoint, f"tool {tool_uuid}")


def _fan_out_over_metrics(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    provider: str,
    organization: str,
    endpoint_config: CodacyEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    endpoint = endpoint_config.name
    body = _metrics_request_body()
    for metric in _list_ready_metrics(session, headers, logger, provider, organization):
        path = endpoint_config.path.format(provider=provider, organization=organization, metric=metric)
        try:
            for page in _paginate(
                session,
                headers,
                logger,
                path,
                endpoint_config.method,
                endpoint_config.extra_params,
                max_pages=endpoint_config.max_pages_per_parent,
                body=body,
            ):
                yield [_normalize_item(endpoint, item, {"metricName": metric}) for item in page]
        except requests.HTTPError as exc:
            _skip_missing_parent(exc, logger, endpoint, f"metric {metric}")


def get_rows(
    api_token: str,
    provider: str,
    organization: str,
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    endpoint_config = CODACY_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)
    # One session reused across every page (and fan-out parent) so urllib3 keeps the connection
    # alive instead of re-handshaking per request. The token rides the custom `api-token`
    # header, which the capture pipeline's name-based denylist doesn't know, so redact it
    # by value.
    session = make_tracked_session(redact_values=(api_token,), capture=endpoint_config.capture_http_samples)

    if endpoint_config.fan_out == "repository":
        yield from _fan_out_over_repositories(session, headers, logger, provider, organization, endpoint_config)
    elif endpoint_config.fan_out == "commit":
        yield from _fan_out_over_commits(session, headers, logger, provider, organization, endpoint_config)
    elif endpoint_config.fan_out == "pull_request":
        yield from _fan_out_over_pull_requests(session, headers, logger, provider, organization, endpoint_config)
    elif endpoint_config.fan_out == "tool":
        yield from _fan_out_over_tools(session, headers, logger, endpoint_config)
    elif endpoint_config.fan_out == "metric":
        yield from _fan_out_over_metrics(session, headers, logger, provider, organization, endpoint_config)
    else:
        path = endpoint_config.path.format(provider=provider, organization=organization)
        for page in _paginate(session, headers, logger, path, endpoint_config.method, endpoint_config.extra_params):
            yield [_normalize_item(endpoint, item) for item in page]


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
        response = make_tracked_session(redact_values=(api_token,)).get(
            url, headers=_get_headers(api_token), timeout=10
        )
        return response.status_code == 200
    except Exception:
        return False
