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
from products.warehouse_sources.backend.temporal.data_imports.sources.semgrep.settings import (
    SEMGREP_ENDPOINTS,
    SemgrepEndpointConfig,
)

SEMGREP_BASE_URL = "https://semgrep.dev/api/v1"
REQUEST_TIMEOUT_SECONDS = 60


class SemgrepRetryableError(Exception):
    pass


@dataclasses.dataclass
class SemgrepResumeConfig:
    # Deployment being processed when the state was saved. Semgrep tokens currently scope to a
    # single deployment, but the fan-out iterates whatever /deployments returns, so the bookmark
    # is a stable deployment id rather than a positional index.
    deployment_id: str | None = None
    # Next zero-indexed page for page-numbered endpoints (projects, findings).
    page: int = 0
    # Next cursor for the cursor-paginated secrets endpoint.
    cursor: str | None = None


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _make_session(api_token: str) -> requests.Session:
    # `redact_values` masks the bearer token in logged URLs and captured HTTP samples so a failed
    # or sampled request can never persist the raw Semgrep credential in PostHog's HTTP telemetry.
    # `capture=False` keeps response bodies out of sample capture entirely: findings and secrets
    # payloads carry security-sensitive detail (secret finding locations, free-form triage
    # comments) the name-based scrubbers can't recognise.
    return make_tracked_session(headers=_get_headers(api_token), redact_values=(api_token,), capture=False)


def _build_url(path: str, params: dict[str, Any]) -> str:
    query = {key: value for key, value in params.items() if value is not None and value != ""}
    if not query:
        return f"{SEMGREP_BASE_URL}{path}"
    return f"{SEMGREP_BASE_URL}{path}?{urlencode(query)}"


@retry(
    retry=retry_if_exception_type((SemgrepRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict[str, Any]:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise SemgrepRetryableError(f"Semgrep API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Don't log the response body: it can echo back request details we'd rather not persist.
        logger.error(f"Semgrep API error: status={response.status_code}, url={url}")
        response.raise_for_status()

    data = response.json()
    # Every endpoint wraps its rows in a JSON object. A non-object 200 is a permanent API-contract
    # violation (proxy HTML, ...), not a transient failure — raise a plain ValueError so it
    # surfaces immediately instead of burning the retry budget on something retries can't fix.
    if not isinstance(data, dict):
        raise ValueError(f"Semgrep API returned a non-object response: url={url}")
    return data


def validate_credentials(api_token: str) -> bool:
    # One cheap probe of the token itself: /deployments is the root resource every Web API token
    # can read, and it's the same call the sync fans out from.
    try:
        response = _make_session(api_token).get(f"{SEMGREP_BASE_URL}/deployments", timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _list_deployments(session: requests.Session, logger: FilteringBoundLogger) -> list[dict[str, Any]]:
    data = _fetch_page(session, f"{SEMGREP_BASE_URL}/deployments", logger)
    return data.get("deployments") or []


def _with_deployment(rows: list[dict[str, Any]], deployment: dict[str, Any]) -> list[dict[str, Any]]:
    """Inject the parent deployment onto each fan-out row so rows stay unique table-wide."""
    return [{**row, "deployment_id": deployment.get("id"), "deployment_slug": deployment.get("slug")} for row in rows]


def _iter_paged_rows(
    session: requests.Session,
    path: str,
    config: SemgrepEndpointConfig,
    deployment: dict[str, Any],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SemgrepResumeConfig],
    start_page: int,
) -> Iterator[list[dict[str, Any]]]:
    page = start_page
    while True:
        url = _build_url(path, {**config.params, "page": page, "page_size": config.page_size})
        data = _fetch_page(session, url, logger)
        rows = data.get(config.data_key) or []
        if not rows:
            break

        yield _with_deployment(rows, deployment)

        # A short page means we've reached the end of the resource.
        if config.page_size is not None and len(rows) < config.page_size:
            break

        page += 1
        # Save AFTER yielding so a crash re-pulls from the last persisted page rather than
        # skipping ahead; the merge dedupes any re-pulled rows on the primary key.
        resumable_source_manager.save_state(SemgrepResumeConfig(deployment_id=str(deployment["id"]), page=page))


def _iter_cursor_rows(
    session: requests.Session,
    path: str,
    config: SemgrepEndpointConfig,
    deployment: dict[str, Any],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SemgrepResumeConfig],
    start_cursor: str | None,
) -> Iterator[list[dict[str, Any]]]:
    cursor = start_cursor
    while True:
        params: dict[str, Any] = {**config.params, "limit": config.page_size}
        if cursor:
            params["cursor"] = cursor
        data = _fetch_page(session, _build_url(path, params), logger)
        rows = data.get(config.data_key) or []
        if not rows:
            break

        yield _with_deployment(rows, deployment)

        next_cursor = data.get("cursor")
        # The API isn't explicit about the final page's cursor; treat a missing or unchanged
        # cursor as the end so we can't loop on the same page forever.
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
        resumable_source_manager.save_state(SemgrepResumeConfig(deployment_id=str(deployment["id"]), cursor=cursor))


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SemgrepResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = SEMGREP_ENDPOINTS[endpoint]
    # One session reused across every page (and every deployment) so urllib3 keeps the
    # connection alive instead of re-handshaking per request.
    session = _make_session(api_token)

    if config.pagination == "none":
        data = _fetch_page(session, _build_url(config.path, dict(config.params)), logger)
        rows = data.get(config.data_key) or []
        if rows:
            yield rows
        return

    deployments = _list_deployments(session, logger)

    # Resolve the saved deployment bookmark to the slice still to process. If the bookmarked
    # deployment no longer exists, start over from the first one — merge dedupes re-pulled rows.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = deployments
    if resume is not None and resume.deployment_id is not None:
        deployment_ids = [str(d.get("id")) for d in deployments]
        if resume.deployment_id in deployment_ids:
            remaining = deployments[deployment_ids.index(resume.deployment_id) :]
            logger.debug(f"Semgrep: resuming {endpoint} from deployment_id={resume.deployment_id}")
        else:
            resume = None

    for index, deployment in enumerate(remaining):
        path = config.path.format(deployment_slug=deployment.get("slug", ""), deployment_id=deployment.get("id", ""))
        # Only the resumed-into deployment starts from the saved page/cursor; the rest start fresh.
        start_page = resume.page if resume is not None else 0
        start_cursor = resume.cursor if resume is not None else None
        resume = None

        if config.pagination == "page":
            yield from _iter_paged_rows(session, path, config, deployment, logger, resumable_source_manager, start_page)
        else:
            yield from _iter_cursor_rows(
                session, path, config, deployment, logger, resumable_source_manager, start_cursor
            )

        # Advance the bookmark so a crash between deployments resumes at the next one.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(SemgrepResumeConfig(deployment_id=str(remaining[index + 1]["id"])))


def semgrep_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SemgrepResumeConfig],
) -> SourceResponse:
    config = SEMGREP_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
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
        sort_mode=config.sort_mode,
    )
