import re
import dataclasses
from collections.abc import Callable, Iterator
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.circleci_insights.settings import (
    CIRCLECI_INSIGHTS_ENDPOINTS,
    DEFAULT_REPORTING_WINDOW,
    REPORTING_WINDOWS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CIRCLECI_BASE_URL = "https://circleci.com/api/v2"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
# Insights list endpoints return token-paginated pages (~250 runs / ~20 aggregates per page).
# Aggregate listings are one row per workflow/job name so stay tiny; runs are bounded by
# CircleCI's ~90-day Insights retention, so the caps below are generous runaway guards.
MAX_METRIC_PAGES = 100
MAX_RUN_PAGES_PER_WORKFLOW = 500
# CircleCI rate-limits per token (not officially documented); 429s carry RateLimit-* headers
# we honor before retrying.
MAX_RATE_LIMIT_SLEEP_SECONDS = 120

PROJECT_SLUG_RE = re.compile(r"^[^/\s]+/[^/\s]+/[^/\s]+$")


class CircleciInsightsRetryableError(Exception):
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
    if isinstance(exc, CircleciInsightsRetryableError) and exc.retry_after:
        return exc.retry_after
    return _EXPONENTIAL_WAIT(retry_state)


@dataclasses.dataclass
class CircleciInsightsResumeConfig:
    # Project slug (or org slug for org-level endpoints) the sync was working through.
    slug: str
    # Workflow the fan-out was inside, for per-workflow endpoints.
    workflow_name: str | None = None
    # Page token to resume the in-progress listing from.
    next_page_token: str | None = None
    # True once every page of `slug` has been yielded, so a resume skips it entirely
    # instead of re-syncing it from the start.
    slug_done: bool = False


def parse_project_slugs(raw: str) -> list[str]:
    """Split the user-entered project slugs field (comma/newline separated) into an ordered,
    de-duplicated list of `vcs/org/repo` slugs."""
    slugs: list[str] = []
    for part in re.split(r"[,\n]", raw or ""):
        slug = part.strip().strip("/")
        if slug and slug not in slugs:
            slugs.append(slug)
    return slugs


def org_slugs_from_projects(project_slugs: list[str]) -> list[str]:
    """Derive the org slugs (`vcs/org`) covered by the configured project slugs."""
    orgs: list[str] = []
    for slug in project_slugs:
        parts = slug.split("/")
        if len(parts) < 2:
            continue
        org = f"{parts[0]}/{parts[1]}"
        if org not in orgs:
            orgs.append(org)
    return orgs


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


def _format_start_date(value: Any) -> str | None:
    """Format the incremental cursor as the date-only ISO 8601 string the `start-date` param
    accepts. Date-only granularity re-reads the watermark day on every sync; the overlap is
    deduped by the primary-key merge and avoids any ambiguity in the API's datetime parsing."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value[:10]
    return None


def validate_credentials(api_token: str, project_slugs_raw: str) -> tuple[bool, str | None]:
    """Confirm the token with /me, then confirm each configured project slug resolves against
    the Insights API."""
    project_slugs = parse_project_slugs(project_slugs_raw)
    if not project_slugs:
        return False, "Enter at least one project slug in `vcs/org/repo` format, e.g. `gh/your-org/your-repo`."

    for slug in project_slugs:
        if not PROJECT_SLUG_RE.match(slug):
            return (
                False,
                f"Project slug '{slug}' is not in the expected `vcs/org/repo` format, e.g. `gh/your-org/your-repo`.",
            )

    session = make_tracked_session(redact_values=(api_token,))
    headers = _get_headers(api_token)

    try:
        response = session.get(f"{CIRCLECI_BASE_URL}/me", headers=headers, timeout=10)
    except Exception:
        return False, "Could not reach the CircleCI API. Please try again."

    if response.status_code != 200:
        return False, "Invalid CircleCI API token. Please check your personal API token."

    for slug in project_slugs:
        try:
            response = session.get(
                _build_url(
                    f"/insights/{quote(slug, safe='/')}/workflows",
                    {"reporting-window": "last-24-hours"},
                ),
                headers=headers,
                timeout=10,
            )
        except Exception:
            return False, "Could not reach the CircleCI API. Please try again."

        if response.status_code != 200:
            return (
                False,
                f"CircleCI project '{slug}' was not found or is not accessible with this token. "
                "Use the `vcs/org/repo` format, e.g. `gh/your-org/your-repo`.",
            )

    return True, None


def _make_fetch_page(api_token: str, logger: FilteringBoundLogger) -> FetchPageFn:
    headers = _get_headers(api_token)
    # Single session reused across pages/retries so connection pooling and per-session
    # tracking hold; redact_values masks the token regardless of header-name denylists.
    session = make_tracked_session(redact_values=(api_token,))

    @retry(
        retry=retry_if_exception_type((CircleciInsightsRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=_retry_wait,
        reraise=True,
    )
    def fetch_page(url: str) -> dict[str, Any]:
        response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429:
            sleep_seconds = _rate_limit_sleep_seconds(response)
            logger.debug(f"CircleCI Insights: rate limited, retrying after {sleep_seconds}s. url={url}")
            raise CircleciInsightsRetryableError(
                f"CircleCI API rate limited: status=429, url={url}", retry_after=sleep_seconds
            )

        if response.status_code >= 500:
            raise CircleciInsightsRetryableError(
                f"CircleCI API error (retryable): status={response.status_code}, url={url}"
            )

        if not response.ok:
            logger.error(f"CircleCI Insights API error: status={response.status_code}, body={response.text}, url={url}")
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
    """Yield ``(items, next_page_token)`` per page of a token-paginated Insights list endpoint."""
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
                f"CircleCI Insights: page cap reached for {resource}, stopping pagination. "
                f"max_pages={max_pages}, path={path}"
            )
            return

        page_token = next_token


def _branch_params(all_branches: bool) -> dict[str, Any]:
    # Omitting the param means the project's default branch; all-branches=true widens to every branch.
    return {"all-branches": "true"} if all_branches else {}


def _discover_workflow_names(
    fetch_page: FetchPageFn,
    project_slug: str,
    all_branches: bool,
    logger: FilteringBoundLogger,
) -> list[str]:
    """List the workflow names Insights knows for a project, from the workflow metrics listing.
    Always uses the widest reporting window so fan-out doesn't miss workflows that only ran
    early in the retention period."""
    names: list[str] = []
    for items, _ in _iter_pages(
        fetch_page,
        f"/insights/{quote(project_slug, safe='/')}/workflows",
        {"reporting-window": "last-90-days", **_branch_params(all_branches)},
        logger,
        max_pages=MAX_METRIC_PAGES,
        resource=f"workflow discovery for {project_slug}",
    ):
        for item in items:
            name = item.get("name")
            if name and name not in names:
                names.append(name)
    return names


def _validate_reporting_window(reporting_window: str | None) -> str:
    if reporting_window in REPORTING_WINDOWS:
        return reporting_window
    return DEFAULT_REPORTING_WINDOW


def get_rows(
    api_token: str,
    project_slugs_raw: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CircleciInsightsResumeConfig],
    reporting_window: str | None = None,
    all_branches: bool = False,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    if endpoint not in CIRCLECI_INSIGHTS_ENDPOINTS:
        raise ValueError(f"Unknown CircleCI Insights endpoint: {endpoint}")

    config = CIRCLECI_INSIGHTS_ENDPOINTS[endpoint]
    window = _validate_reporting_window(reporting_window)
    project_slugs = parse_project_slugs(project_slugs_raw)
    slugs = org_slugs_from_projects(project_slugs) if config.org_level else project_slugs

    fetch_page = _make_fetch_page(api_token, logger)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.slug not in slugs:
        # The configured slugs changed since the state was saved; start from scratch.
        resume = None
    if resume is not None:
        logger.debug(f"CircleCI Insights: resuming {endpoint} from slug {resume.slug}")

    for slug in slugs:
        slug_resume: CircleciInsightsResumeConfig | None = None
        if resume is not None:
            if slug != resume.slug:
                # Slugs before the resume point were fully synced before the interruption.
                continue
            slug_resume, resume = resume, None
            if slug_resume.slug_done:
                continue

        if endpoint == "workflow_metrics":
            yield from _project_workflow_metrics_rows(
                fetch_page, slug, window, all_branches, logger, resumable_source_manager, slug_resume
            )
        elif endpoint in ("workflow_runs", "job_metrics"):
            yield from _project_workflow_fan_out_rows(
                fetch_page,
                slug,
                endpoint,
                window,
                all_branches,
                logger,
                resumable_source_manager,
                slug_resume,
                should_use_incremental_field,
                db_incremental_field_last_value,
            )
        elif endpoint == "flaky_tests":
            yield from _project_flaky_tests_rows(fetch_page, slug, logger)
        elif endpoint == "org_summary_metrics":
            yield from _org_summary_rows(fetch_page, slug, window, logger)

        # Mark the slug fully synced so a resume moves straight to the next one.
        resumable_source_manager.save_state(CircleciInsightsResumeConfig(slug=slug, slug_done=True))


def _project_workflow_metrics_rows(
    fetch_page: FetchPageFn,
    project_slug: str,
    window: str,
    all_branches: bool,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CircleciInsightsResumeConfig],
    slug_resume: CircleciInsightsResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    start_token = slug_resume.next_page_token if slug_resume is not None else None
    for items, next_token in _iter_pages(
        fetch_page,
        f"/insights/{quote(project_slug, safe='/')}/workflows",
        {"reporting-window": window, **_branch_params(all_branches)},
        logger,
        max_pages=MAX_METRIC_PAGES,
        resource=f"workflow metrics for {project_slug}",
        start_token=start_token,
    ):
        if items:
            yield [{**item, "project_slug": project_slug} for item in items]
        # Save state after the page's rows have been yielded, so a crash re-yields the
        # in-progress page (merge dedupes on primary key) instead of skipping it.
        if next_token:
            resumable_source_manager.save_state(
                CircleciInsightsResumeConfig(slug=project_slug, next_page_token=next_token)
            )


def _project_workflow_fan_out_rows(
    fetch_page: FetchPageFn,
    project_slug: str,
    endpoint: str,
    window: str,
    all_branches: bool,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CircleciInsightsResumeConfig],
    slug_resume: CircleciInsightsResumeConfig | None,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    config = CIRCLECI_INSIGHTS_ENDPOINTS[endpoint]
    workflow_names = _discover_workflow_names(fetch_page, project_slug, all_branches, logger)

    params: dict[str, Any] = {**_branch_params(all_branches)}
    if config.takes_reporting_window:
        params["reporting-window"] = window
    if endpoint == "workflow_runs" and should_use_incremental_field:
        start_date = _format_start_date(db_incremental_field_last_value)
        if start_date:
            # Server-side filter: every page of the runs listing only returns runs created on
            # or after this date (the filter rides along with the page token on later pages).
            params["start-date"] = start_date

    max_pages = MAX_RUN_PAGES_PER_WORKFLOW if endpoint == "workflow_runs" else MAX_METRIC_PAGES

    resume_workflow = slug_resume.workflow_name if slug_resume is not None else None
    if resume_workflow is not None and resume_workflow not in workflow_names:
        # The workflow disappeared from the listing since the state was saved; walk them all.
        resume_workflow = None

    for workflow_name in workflow_names:
        start_token: str | None = None
        if resume_workflow is not None:
            if workflow_name != resume_workflow:
                # Workflows before the resume point were fully synced before the interruption.
                continue
            start_token = slug_resume.next_page_token if slug_resume is not None else None
            resume_workflow = None

        path = config.path.format(slug=quote(project_slug, safe="/"), workflow_name=quote(workflow_name, safe=""))
        for items, next_token in _iter_pages(
            fetch_page,
            path,
            params,
            logger,
            max_pages=max_pages,
            resource=f"{endpoint} for {project_slug} workflow {workflow_name}",
            start_token=start_token,
        ):
            if items:
                yield [{**item, "project_slug": project_slug, "workflow_name": workflow_name} for item in items]
            if next_token:
                resumable_source_manager.save_state(
                    CircleciInsightsResumeConfig(
                        slug=project_slug, workflow_name=workflow_name, next_page_token=next_token
                    )
                )


def _project_flaky_tests_rows(
    fetch_page: FetchPageFn,
    project_slug: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    data = fetch_page(_build_url(f"/insights/{quote(project_slug, safe='/')}/flaky-tests"))
    flaky_tests = data.get("flaky_tests") or []
    if flaky_tests:
        yield [{**item, "project_slug": project_slug} for item in flaky_tests]


def _org_summary_rows(
    fetch_page: FetchPageFn,
    org_slug: str,
    window: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    # The org summary endpoint is auth-gated (org membership required), so its response shape
    # could not be verified against the live API; parsing follows the documented
    # {org_data, org_project_data} envelope and degrades to zero rows on an unexpected shape.
    data = fetch_page(_build_url(f"/insights/{quote(org_slug, safe='/')}/summary", {"reporting-window": window}))
    project_rows = data.get("org_project_data")
    if not isinstance(project_rows, list):
        logger.warning(f"CircleCI Insights: unexpected org summary response shape for {org_slug}, syncing zero rows")
        return
    rows = [{**item, "org_slug": org_slug} for item in project_rows if isinstance(item, dict)]
    if rows:
        yield rows


def circleci_insights_source(
    api_token: str,
    project_slugs_raw: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CircleciInsightsResumeConfig],
    reporting_window: str | None = None,
    all_branches: bool = False,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CIRCLECI_INSIGHTS_ENDPOINTS[endpoint]
    partition_key: Optional[str] = config.partition_key

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            project_slugs_raw=project_slugs_raw,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            reporting_window=reporting_window,
            all_branches=all_branches,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=list(config.primary_keys),
        # The runs listing returns newest-first with no sort param (verified live); the
        # aggregate listings have no meaningful row order.
        sort_mode="desc" if endpoint == "workflow_runs" else "asc",
        partition_count=1 if partition_key else None,
        partition_size=1 if partition_key else None,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
    )
