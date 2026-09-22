from collections.abc import Callable, Iterator
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.circleci.settings import CIRCLECI_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

CIRCLECI_BASE_URL = "https://circleci.com/api/v2"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
# Most CircleCI v2 list endpoints return ~20 items per page and don't accept a page-size param,
# so the caps below bound the scan in pages, not rows.
MAX_PIPELINE_PAGES = 500
MAX_WORKFLOW_PAGES_PER_PIPELINE = 10
MAX_JOB_PAGES_PER_WORKFLOW = 25
MAX_COMPONENT_PAGES = 200
MAX_VERSION_PAGES_PER_COMPONENT = 25
# The deploy components endpoint is the exception: page size is required and no maximum is
# documented, so we ask for the same ~20 items the other list endpoints return by default.
COMPONENTS_PAGE_SIZE = 20
# CircleCI rate-limits at roughly 1000 requests/minute per token (not officially documented);
# 429s carry RateLimit-* headers we honor before retrying.
MAX_RATE_LIMIT_SLEEP_SECONDS = 120
# Endpoints served by the deploy components scan rather than the pipelines scan.
COMPONENT_SCAN_ENDPOINTS = frozenset({"components", "component_versions"})
# Workflow fields naming a CircleCI user, which is how the users stream discovers actor ids.
WORKFLOW_ACTOR_FIELDS = ("started_by", "canceled_by", "errored_by")
# A version row's identity beyond the component id. None of these are documented as required,
# and a null merge key re-inserts the row on every sync, so they collapse to an empty string.
VERSION_KEY_FIELDS = ("environment_id", "namespace", "name")


class CircleCIRetryableError(Exception):
    def __init__(self, message: str, retry_after: int = 0) -> None:
        super().__init__(message)
        # Seconds the API asked us to wait (from Retry-After/RateLimit-Reset); 0 when unknown.
        self.retry_after = retry_after


# Returns the decoded body: an object for most endpoints, a list for /me/collaborations.
FetchPageFn = Callable[[str], Any]

_EXPONENTIAL_WAIT = wait_exponential_jitter(initial=1, max=60)


def _retry_wait(retry_state: RetryCallState) -> float:
    # Honor the API's Retry-After exactly once; otherwise back off exponentially. Doing the
    # wait here (rather than time.sleep inside fetch_page) avoids stacking both delays.
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, CircleCIRetryableError) and exc.retry_after:
        return exc.retry_after
    return _EXPONENTIAL_WAIT(retry_state)


@frozen
class CircleCIResumeConfig:
    # Page token for the endpoint's top-level scan (pipelines, or deploy components for the
    # components streams). Fan-out streams also resume on it: children of fully processed
    # parent pages have already been yielded, and the in-progress page is re-yielded then
    # deduped on primary key. Resume state is keyed per job, so the two scans never mix.
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
    def fetch_page(url: str) -> Any:
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

        if next_token == page_token:
            # CircleCI ends a list with a null next_page_token, never with a repeat, so the
            # endpoint ignored our page-token and is serving the same page again. Stopping
            # here would publish a truncated table on a full refresh, so fail the run.
            raise ValueError(
                f"CircleCI returned the same page token twice for {resource}, so pagination cannot advance. path={path}"
            )

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


def _resolve_org_id(fetch_page: FetchPageFn, org_slug: str) -> str:
    # The deploy endpoints take an organization UUID, which the v2 API only exposes through the
    # collaborations list for the token's user.
    for collaboration in fetch_page(_build_url("/me/collaborations")) or []:
        if collaboration.get("slug") == org_slug and collaboration.get("id"):
            return collaboration["id"]

    raise ValueError(
        f"CircleCI organization '{org_slug}' was not found for this token, so its deploy "
        "components cannot be looked up."
    )


def _iter_component_pages(
    fetch_page: FetchPageFn,
    org_slug: str,
    logger: FilteringBoundLogger,
    start_token: str | None,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    yield from _iter_pages(
        fetch_page,
        "/deploy/components",
        {"org-id": _resolve_org_id(fetch_page, org_slug), "page-size": COMPONENTS_PAGE_SIZE},
        logger,
        max_pages=MAX_COMPONENT_PAGES,
        resource="components",
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


def _workflow_rows(
    fetch_page: FetchPageFn, pipelines: list[dict[str, Any]], logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    for pipeline in pipelines:
        yield from _workflows_for_pipeline(fetch_page, pipeline["id"], logger)


def _job_rows(
    fetch_page: FetchPageFn, pipelines: list[dict[str, Any]], logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    for pipeline in pipelines:
        for workflows in _workflows_for_pipeline(fetch_page, pipeline["id"], logger):
            for workflow in workflows:
                for jobs in _jobs_for_workflow(fetch_page, workflow["id"], logger):
                    # Job rows only carry project_slug natively; inject parent identifiers
                    # plus the workflow's created_at as a stable partition key (jobs expose
                    # no creation timestamp of their own, and started_at is null for
                    # unstarted/approval jobs).
                    yield [
                        {
                            **job,
                            "pipeline_id": pipeline["id"],
                            "workflow_id": workflow["id"],
                            "workflow_created_at": workflow.get("created_at"),
                        }
                        for job in jobs
                    ]


def _project_rows(
    fetch_page: FetchPageFn, pipelines: list[dict[str, Any]], seen_project_slugs: set[str]
) -> Iterator[list[dict[str, Any]]]:
    # v2 has no "list projects in org" endpoint, so distinct project slugs are discovered
    # from the pipelines scan and resolved via GET /project/{slug}.
    for pipeline in pipelines:
        project_slug = pipeline.get("project_slug")
        if not project_slug or project_slug in seen_project_slugs:
            continue
        seen_project_slugs.add(project_slug)
        project = fetch_page(_build_url(f"/project/{quote(project_slug, safe='/')}"))
        yield [project]


def _component_version_rows(
    fetch_page: FetchPageFn, components: list[dict[str, Any]], logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    for component in components:
        component_id = component["id"]
        for versions, _ in _iter_pages(
            fetch_page,
            f"/deploy/components/{component_id}/versions",
            {},
            logger,
            max_pages=MAX_VERSION_PAGES_PER_COMPONENT,
            resource=f"versions of component {component_id}",
        ):
            if versions:
                yield [
                    {
                        **version,
                        "component_id": component_id,
                        **{key: version.get(key) or "" for key in VERSION_KEY_FIELDS},
                    }
                    for version in versions
                ]


def _user_rows(
    fetch_page: FetchPageFn,
    pipelines: list[dict[str, Any]],
    logger: FilteringBoundLogger,
    seen_user_ids: set[str],
) -> Iterator[list[dict[str, Any]]]:
    # v2 has no "list users in org" endpoint, so the actor ids carried on workflows are
    # resolved one at a time via GET /user/{id}.
    for pipeline in pipelines:
        for workflows in _workflows_for_pipeline(fetch_page, pipeline["id"], logger):
            for workflow in workflows:
                for field_name in WORKFLOW_ACTOR_FIELDS:
                    user_id = workflow.get(field_name)
                    if not user_id or user_id in seen_user_ids:
                        continue
                    seen_user_ids.add(user_id)
                    try:
                        user = fetch_page(_build_url(f"/user/{quote(str(user_id), safe='')}"))
                    except requests.HTTPError as error:
                        # A workflow can name an actor whose CircleCI account is gone; one
                        # stale id must not fail the whole stream.
                        if error.response is not None and error.response.status_code == 404:
                            continue
                        raise
                    yield [user]


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

    # Project slugs and user ids already emitted this run. Lost on resume, which only causes
    # re-fetch/re-yield of a few rows — merge dedupes on primary key.
    seen_project_slugs: set[str] = set()
    seen_user_ids: set[str] = set()

    if endpoint in COMPONENT_SCAN_ENDPOINTS:
        pages = _iter_component_pages(fetch_page, org_slug, logger, start_token)
    else:
        pages = _iter_pipeline_pages(fetch_page, org_slug, logger, start_token)

    for items, next_token in pages:
        if endpoint == "pipelines":
            if items:
                yield items
        elif endpoint == "workflows":
            yield from _workflow_rows(fetch_page, items, logger)
        elif endpoint == "jobs":
            yield from _job_rows(fetch_page, items, logger)
        elif endpoint == "projects":
            yield from _project_rows(fetch_page, items, seen_project_slugs)
        elif endpoint == "users":
            yield from _user_rows(fetch_page, items, logger, seen_user_ids)
        elif endpoint == "components":
            if items:
                yield items
        elif endpoint == "component_versions":
            yield from _component_version_rows(fetch_page, items, logger)

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
        primary_keys=list(config.primary_keys),
        # No v2 list endpoint takes a sort param, and the ones that document an order return
        # newest-first. Every stream is full refresh, so this is advisory.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
    )
