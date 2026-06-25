import dataclasses
from collections.abc import Callable, Iterator
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.circleci.settings import CIRCLECI_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CIRCLECI_BASE_URL = "https://circleci.com/api/v2"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
# CircleCI v2 list endpoints return ~20 items per page and don't accept a page-size param,
# so the caps below bound the scan in pages, not rows.
MAX_PIPELINE_PAGES = 500
MAX_WORKFLOW_PAGES_PER_PIPELINE = 10
MAX_JOB_PAGES_PER_WORKFLOW = 25
# CircleCI rate-limits at roughly 1000 requests/minute per token (not officially documented);
# 429s carry RateLimit-* headers we honor before retrying.
MAX_RATE_LIMIT_SLEEP_SECONDS = 120


class CircleCIRetryableError(Exception):
    def __init__(self, message: str, retry_after: int = 0) -> None:
        super().__init__(message)
        # Seconds the API asked us to wait (from Retry-After/RateLimit-Reset); 0 when unknown.
        self.retry_after = retry_after


FetchPageFn = Callable[[str], dict[str, Any]]

_EXPONENTIAL_WAIT = wait_exponential_jitter(initial=1, max=60)


def _retry_wait(retry_state: RetryCallState) -> float:
    # Honor the API's Retry-After exactly once; otherwise back off exponentially. Doing the
    # wait here (rather than time.sleep inside fetch_page) avoids stacking both delays.
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, CircleCIRetryableError) and exc.retry_after:
        return exc.retry_after
    return _EXPONENTIAL_WAIT(retry_state)


@dataclasses.dataclass
class CircleCIResumeConfig:
    # Page token for the top-level pipelines scan. Fan-out streams (workflows/jobs/projects)
    # also resume on this token: children of fully processed pipeline pages have already been
    # yielded, and the in-progress page is re-yielded then deduped on primary key.
    next_page_token: str


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Circle-Token": api_token,
        "Accept": "application/json",
    }


def _build_url(path: str, params: dict[str, Any] | None = None) -> str:
    clean_params = {key: value for key, value in (params or {}).items() if value is not None}
    if not clean_params:
        return f"{CIRCLECI_BASE_URL}{path}"
    return f"{CIRCLECI_BASE_URL}{path}?{urlencode(clean_params)}"


def _rate_limit_sleep_seconds(response: requests.Response) -> int:
    # Prefer Retry-After, fall back to RateLimit-Reset. Header semantics (seconds-to-wait vs
    # epoch) aren't officially documented, so anything outside a sane window is clamped.
    for header in ("retry-after", "ratelimit-reset", "x-ratelimit-reset"):
        raw = response.headers.get(header)
        if raw is None:
            continue
        try:
            seconds = int(float(raw))
        except (TypeError, ValueError):
            continue
        return max(0, min(seconds, MAX_RATE_LIMIT_SLEEP_SECONDS))
    return 0


def validate_credentials(api_token: str, org_slug: str | None = None) -> tuple[bool, str | None]:
    """Confirm the token with /me, then (when provided) confirm the org slug resolves."""
    session = make_tracked_session(redact_values=(api_token,))
    headers = _get_headers(api_token)

    try:
        response = session.get(f"{CIRCLECI_BASE_URL}/me", headers=headers, timeout=10)
    except Exception:
        return False, "Could not reach the CircleCI API. Please try again."

    if response.status_code != 200:
        return False, "Invalid CircleCI API token. Please check your personal API token."

    if not org_slug:
        return True, None

    try:
        response = session.get(
            _build_url("/pipeline", {"org-slug": org_slug}),
            headers=headers,
            timeout=10,
        )
    except Exception:
        return False, "Could not reach the CircleCI API. Please try again."

    if response.status_code != 200:
        return (
            False,
            f"CircleCI organization '{org_slug}' was not found or is not accessible with this token. "
            "Use the `vcs/org` format, e.g. `gh/your-org`.",
        )

    return True, None


def _make_fetch_page(api_token: str, logger: FilteringBoundLogger) -> FetchPageFn:
    headers = _get_headers(api_token)
    # Single session reused across pages/retries so connection pooling and per-session
    # tracking hold; redact_values masks the token regardless of header-name denylists.
    session = make_tracked_session(redact_values=(api_token,))

    @retry(
        retry=retry_if_exception_type((CircleCIRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=_retry_wait,
        reraise=True,
    )
    def fetch_page(url: str) -> dict[str, Any]:
        response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429:
            sleep_seconds = _rate_limit_sleep_seconds(response)
            logger.debug(f"CircleCI: rate limited, retrying after {sleep_seconds}s. url={url}")
            raise CircleCIRetryableError(f"CircleCI API rate limited: status=429, url={url}", retry_after=sleep_seconds)

        if response.status_code >= 500:
            raise CircleCIRetryableError(f"CircleCI API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"CircleCI API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    return fetch_page


def _iter_pages(
    fetch_page: FetchPageFn,
    path: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
    max_pages: int,
    resource: str,
    start_token: str | None = None,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    """Yield ``(items, next_page_token)`` per page of a token-paginated v2 list endpoint."""
    page_token = start_token
    pages_fetched = 0

    while True:
        data = fetch_page(_build_url(path, {**params, "page-token": page_token}))
        items = data.get("items") or []
        next_token = data.get("next_page_token")
        pages_fetched += 1

        yield items, next_token

        if not next_token:
            return

        if pages_fetched >= max_pages:
            logger.warning(
                f"CircleCI: page cap reached for {resource}, stopping pagination. max_pages={max_pages}, path={path}"
            )
            return

        page_token = next_token


def _iter_pipeline_pages(
    fetch_page: FetchPageFn,
    org_slug: str,
    logger: FilteringBoundLogger,
    start_token: str | None,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    yield from _iter_pages(
        fetch_page,
        "/pipeline",
        {"org-slug": org_slug},
        logger,
        max_pages=MAX_PIPELINE_PAGES,
        resource="pipelines",
        start_token=start_token,
    )


def _workflows_for_pipeline(
    fetch_page: FetchPageFn, pipeline_id: str, logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    for workflows, _ in _iter_pages(
        fetch_page,
        f"/pipeline/{pipeline_id}/workflow",
        {},
        logger,
        max_pages=MAX_WORKFLOW_PAGES_PER_PIPELINE,
        resource=f"workflows of pipeline {pipeline_id}",
    ):
        if workflows:
            yield workflows


def _jobs_for_workflow(
    fetch_page: FetchPageFn, workflow_id: str, logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    for jobs, _ in _iter_pages(
        fetch_page,
        f"/workflow/{workflow_id}/job",
        {},
        logger,
        max_pages=MAX_JOB_PAGES_PER_WORKFLOW,
        resource=f"jobs of workflow {workflow_id}",
    ):
        if jobs:
            yield jobs


def get_rows(
    api_token: str,
    org_slug: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CircleCIResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    if endpoint not in CIRCLECI_ENDPOINTS:
        raise ValueError(f"Unknown CircleCI endpoint: {endpoint}")

    fetch_page = _make_fetch_page(api_token, logger)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_token = resume_config.next_page_token if resume_config is not None else None
    if start_token is not None:
        logger.debug(f"CircleCI: resuming {endpoint} from saved pipelines page token")

    # Project slugs already emitted by the projects stream this run. Lost on resume, which
    # only causes re-fetch/re-yield of a few project rows — merge dedupes on primary key.
    seen_project_slugs: set[str] = set()

    for pipelines, next_token in _iter_pipeline_pages(fetch_page, org_slug, logger, start_token):
        if endpoint == "pipelines":
            if pipelines:
                yield pipelines
        elif endpoint == "workflows":
            for pipeline in pipelines:
                for workflows in _workflows_for_pipeline(fetch_page, pipeline["id"], logger):
                    yield workflows
        elif endpoint == "jobs":
            for pipeline in pipelines:
                for workflows in _workflows_for_pipeline(fetch_page, pipeline["id"], logger):
                    for workflow in workflows:
                        for jobs in _jobs_for_workflow(fetch_page, workflow["id"], logger):
                            # Job rows only carry project_slug natively; inject parent
                            # identifiers plus the workflow's created_at as a stable
                            # partition key (jobs expose no creation timestamp of their
                            # own, and started_at is null for unstarted/approval jobs).
                            yield [
                                {
                                    **job,
                                    "pipeline_id": pipeline["id"],
                                    "workflow_id": workflow["id"],
                                    "workflow_created_at": workflow.get("created_at"),
                                }
                                for job in jobs
                            ]
        elif endpoint == "projects":
            # v2 has no "list projects in org" endpoint, so distinct project slugs are
            # discovered from the pipelines scan and resolved via GET /project/{slug}.
            for pipeline in pipelines:
                project_slug = pipeline.get("project_slug")
                if not project_slug or project_slug in seen_project_slugs:
                    continue
                seen_project_slugs.add(project_slug)
                project = fetch_page(_build_url(f"/project/{quote(project_slug, safe='/')}"))
                yield [project]

        # Save state after the page's rows (and any fan-out children) have been yielded, so a
        # crash re-yields the in-progress page instead of skipping it.
        if next_token:
            resumable_source_manager.save_state(CircleCIResumeConfig(next_page_token=next_token))


def circleci_source(
    api_token: str,
    org_slug: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CircleCIResumeConfig],
) -> SourceResponse:
    config = CIRCLECI_ENDPOINTS[endpoint]
    partition_key: Optional[str] = config.partition_key

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            org_slug=org_slug,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=[config.primary_key],
        # The API always returns newest-first and exposes no sort param.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
    )
