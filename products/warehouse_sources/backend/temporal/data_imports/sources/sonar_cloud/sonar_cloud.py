import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.sonar_cloud.settings import (
    MAX_PAGE_SIZE,
    REGION_HOSTS,
    RESULT_CAP,
    SONAR_CLOUD_ENDPOINTS,
)


class SonarCloudRetryableError(Exception):
    pass


@dataclasses.dataclass
class SonarCloudResumeConfig:
    # 1-based index of the next page to fetch. Paginated endpoints resume from here after a crash;
    # non-paginated endpoints ignore it.
    page: int = 1


def _base_url(region: str) -> str:
    return REGION_HOSTS.get((region or "eu").lower(), REGION_HOSTS["eu"])


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


@retry(
    retry=retry_if_exception_type(
        (
            SonarCloudRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict[str, Any]:
    response = session.get(url, timeout=60)

    # SonarQube Cloud returns 429 with no documented quota on rate limiting; back off and retry.
    if response.status_code == 429 or response.status_code >= 500:
        raise SonarCloudRetryableError(f"SonarQube Cloud API error (retryable): status={response.status_code}")

    if not response.ok:
        logger.error(f"SonarQube Cloud API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _build_url(base_url: str, path: str, params: dict[str, Any]) -> str:
    query = urlencode({k: v for k, v in params.items() if v is not None})
    return f"{base_url}/{path}?{query}" if query else f"{base_url}/{path}"


def _total(data: dict[str, Any]) -> int | None:
    """Total row count, from either the nested `paging` object or the flat top-level fields."""
    paging = data.get("paging")
    if isinstance(paging, dict) and paging.get("total") is not None:
        return int(paging["total"])
    if data.get("total") is not None:
        return int(data["total"])
    return None


def validate_credentials(token: str, organization: str, region: str, timeout: int = 10) -> int:
    """Probe the projects endpoint and return the HTTP status code (or 0 on transport failure).

    A single cheap request confirms the token is genuine. The caller decides how to treat 403
    (valid token, missing scope) depending on whether it's validating a specific schema.
    """
    url = _build_url(_base_url(region), "components/search_projects", {"organization": organization, "ps": 1})
    try:
        response = make_tracked_session(headers=_headers(token)).get(url, timeout=timeout)
        return response.status_code
    except Exception:
        return 0


def get_rows(
    token: str,
    organization: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SonarCloudResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = SONAR_CLOUD_ENDPOINTS[endpoint]
    base_url = _base_url(region)
    session = make_tracked_session(headers=_headers(token))

    base_params: dict[str, Any] = {}
    if config.requires_organization:
        base_params["organization"] = organization

    if not config.paginated:
        data = _fetch(session, _build_url(base_url, config.path, base_params), logger)
        rows = data.get(config.data_key, [])
        if rows:
            yield rows
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume is not None else 1
    fetched = (page - 1) * MAX_PAGE_SIZE

    while True:
        params = {**base_params, "p": page, "ps": MAX_PAGE_SIZE}
        data = _fetch(session, _build_url(base_url, config.path, params), logger)
        rows = data.get(config.data_key, [])
        if not rows:
            break

        yield rows
        fetched += len(rows)

        total = _total(data)
        # v1 hard-caps results at 10000 regardless of the reported total; stop there to avoid
        # requesting pages the API will reject.
        if len(rows) < MAX_PAGE_SIZE or fetched >= RESULT_CAP or (total is not None and fetched >= total):
            if fetched >= RESULT_CAP and (total is None or total > RESULT_CAP):
                logger.warning(
                    f"SonarQube Cloud endpoint {endpoint} hit the 10000-result cap; rows beyond the cap were not synced"
                )
            break

        page += 1
        # Save after yielding so a crash re-yields the last page (merge dedupes on the primary key)
        # rather than skipping it.
        resumable_source_manager.save_state(SonarCloudResumeConfig(page=page))


def sonar_cloud_source(
    token: str,
    organization: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SonarCloudResumeConfig],
) -> SourceResponse:
    config = SONAR_CLOUD_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            token=token,
            organization=organization,
            region=region,
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
