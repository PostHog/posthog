import re
import dataclasses
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional, cast
from urllib.parse import quote, urljoin, urlparse

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent import (
        ParentTableRef,
    )

import structlog
from dateutil import parser as dateutil_parser
from requests import Request, Response
from requests.exceptions import HTTPError, JSONDecodeError, RequestException
from tenacity import RetryCallState, retry, retry_if_exception_type, retry_if_result, stop_after_attempt

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
    ParentRowFilter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sync_window import SyncWindow
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.sentry.settings import (
    ALLOWED_SENTRY_API_BASE_URLS,
    DEFAULT_SENTRY_API_BASE_URL,
    ISSUES_PARENT_ROW_FILTER,
    PROJECT_STAT_NAMES,
    REQUIRED_SENTRY_SCOPES,
    SENTRY_ENDPOINTS,
    SENTRY_RETENTION_DAYS,
    TRACE_ITEM_DATASETS,
    TRACE_ITEM_STATS_TYPES,
    SentryEndpointConfig,
)

_MAX_PAGES_PER_PARENT = 100
_REQUEST_TIMEOUT = 30
_MAX_RETRIES = 3
_RETRYABLE_STATUS_CODES = (429, 500, 502, 503, 504)
# Safety bound for how many issues the issue_tag_values fan-out will skip while
# fast-forwarding to a saved checkpoint issue. If the checkpoint issue was
# deleted between runs, we'd otherwise skip every remaining issue and yield
# nothing. Once this bound is exceeded we treat the checkpoint as stale and
# fall through to fresh processing of the current and remaining issues.
_RESUME_ISSUE_SKIP_LIMIT = 5000
logger = structlog.get_logger(__name__)


@dataclasses.dataclass
class SentryResumeConfig:
    """Resume state for Sentry endpoints.

    Flat org-level endpoints (projects/teams/members/...) checkpoint the
    ``next_url`` returned by ``SentryPaginator``.

    ``issue_tag_values`` is a three-level hand-rolled fan-out
    (issues -> tags-per-issue -> values-per-tag); its checkpoint is the
    ``(issue_id, tag_key, values_next_url)`` triple pointing at the next
    values page to fetch for that specific (issue, tag) combination.

    Parent/child fan-out endpoints driven by ``build_dependent_resource``
    don't currently checkpoint — the framework does not expose a resume
    hook for dependent resources, so those paths remain non-resumable.
    """

    next_url: Optional[str] = None
    issue_id: Optional[str] = None
    tag_key: Optional[str] = None
    values_next_url: Optional[str] = None
    # Which issue ordering the fan-out checkpoint above is a position in: None for the API's
    # `sort=date` listing, or the pinned Delta version when the parent came from the warehouse.
    # Resuming across a change here would fast-forward past issues the new order never reached.
    parent_version: Optional[int] = None


# Sentry exposes an org URL as `https://<org>.sentry.io/` in its UI and as
# `https://sentry.io/organizations/<org>/...` in deep links, so users routinely paste one of
# those into the slug field instead of the bare slug.
_SENTRY_NON_ORG_SUBDOMAINS = {"www", "us", "de", "eu", "app"}


def _normalize_organization_slug(organization_slug: str) -> str:
    """Pull the org slug out of a pasted Sentry URL.

    A valid Sentry org slug is lowercase alphanumeric plus hyphens, so any `/`, `:`, or `.` in the
    value means it's a URL or host, not a slug. Extract the slug from the two shapes Sentry uses and
    leave a bare slug untouched. Because a real slug can never contain those characters, an input we
    rewrite here would have failed the credential check anyway, so a wrong guess can only produce the
    same failure with a clearer target, never hijack a valid slug.
    """
    slug = organization_slug.strip()
    if not any(char in slug for char in "/:."):
        return slug

    parsed = urlparse(slug if "//" in slug else f"https://{slug}")
    segments = [segment for segment in parsed.path.split("/") if segment]

    if "organizations" in segments:
        index = segments.index("organizations")
        if index + 1 < len(segments):
            return segments[index + 1]

    host = (parsed.hostname or "").lower()
    if host.endswith(".sentry.io"):
        subdomain = host.removesuffix(".sentry.io")
        if subdomain and subdomain not in _SENTRY_NON_ORG_SUBDOMAINS:
            return subdomain

    # Couldn't confidently identify a slug (e.g. a bare `sentry.io` or an `/organizations/` path
    # with no slug after it), so leave the value untouched. The credential check then reports the
    # exact thing the user typed rather than a misleading guess like the literal "organizations".
    return slug


def _normalize_api_base_url(api_base_url: str | None) -> str:
    return (api_base_url or DEFAULT_SENTRY_API_BASE_URL).rstrip("/")


def _validated_api_base_url(api_base_url: str | None) -> str:
    normalized_url = _normalize_api_base_url(api_base_url)
    if normalized_url not in ALLOWED_SENTRY_API_BASE_URLS:
        raise ValueError(
            "API base URL must be one of https://sentry.io, https://us.sentry.io, or https://de.sentry.io."
        )
    return normalized_url


def _auth_headers(auth_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth_token}", "Accept": "application/json"}


def _rest_api_client_config(base_api_url: str, auth_token: str) -> ClientConfig:
    return {
        "base_url": base_api_url,
        "auth": {"type": "bearer", "token": auth_token},
        "headers": {"Accept": "application/json"},
        "paginator": SentryPaginator(),
    }


def _start_param_for_sentry(value: Any) -> str:
    """Format/cap datetime-like values for Sentry `start` and `end` params."""
    normalized_value = coerce_datetime_to_utc(value)
    if normalized_value is None:
        return str(value)

    capped = min(normalized_value, datetime.now(UTC))
    # Keep format conservative for API parsing: no timezone suffix, second precision.
    return capped.strftime("%Y-%m-%dT%H:%M:%S")


def _sentry_incremental_window(cursor_path: str) -> IncrementalConfig:
    return {
        "cursor_path": cursor_path,
        "start_param": "start",
        "end_param": "end",
        "initial_value": "1970-01-01T00:00:00",
        "end_value": _start_param_for_sentry(datetime.now(UTC)),
        "convert": _start_param_for_sentry,
    }


def _retention_floor(now: datetime) -> datetime:
    return now - timedelta(days=SENTRY_RETENTION_DAYS)


def _retention_bounded_start_param(value: Any) -> str:
    """Format a datetime-like value clamped to Sentry's retention window.

    Sessions, stats, replays and Discover all reject a range that reaches further
    back than retention, so the 1970 sentinel used for issues would fail the first
    sync outright.
    """
    now = datetime.now(UTC)
    floor = _retention_floor(now)
    parsed = _parse_datetime_value(value)
    bounded = floor if parsed is None else min(max(parsed, floor), now)
    return bounded.strftime("%Y-%m-%dT%H:%M:%S")


def _sentry_retention_incremental_window(cursor_path: str) -> IncrementalConfig:
    now = datetime.now(UTC)
    return {
        "cursor_path": cursor_path,
        "start_param": "start",
        "end_param": "end",
        "initial_value": _retention_bounded_start_param(_retention_floor(now)),
        "end_value": _start_param_for_sentry(now),
        "convert": _retention_bounded_start_param,
    }


def _retention_window(incremental_value: Any = None) -> SyncWindow[str]:
    now = datetime.now(UTC)
    return SyncWindow(start=_retention_bounded_start_param(incremental_value), end=_start_param_for_sentry(now))


def _parse_next_link(link_header: str) -> str | None:
    if not link_header:
        return None

    for part in link_header.split(","):
        part = part.strip()
        next_match = re.search(r'<([^>]+)>;\s*rel="next"', part)
        if not next_match:
            continue
        results_match = re.search(r'results="(true|false)"', part)
        if results_match and results_match.group(1) == "true":
            return next_match.group(1)
        return None
    return None


class SentryPaginator(BasePaginator):
    """Paginator for Sentry API Link-header cursor pagination."""

    def __init__(self) -> None:
        super().__init__()
        self._next_url: str | None = None

    def init_request(self, request: Request) -> None:
        # When seeded via ``set_resume_state``, the paginator already holds the
        # URL of the next page to fetch; redirect the first request to it so we
        # don't re-issue the initial page before resuming.
        if self._next_url:
            request.url = self._next_url
            request.params = {}

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        link_header = response.headers.get("Link", "")
        self._next_url = _parse_next_link(link_header)
        self._has_next_page = self._next_url is not None

    def update_request(self, request: Request) -> None:
        if self._next_url:
            request.url = self._next_url
            request.params = {}

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._next_url and self._has_next_page:
            return {"next_url": self._next_url}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        next_url = state.get("next_url")
        if next_url:
            self._next_url = next_url
            self._has_next_page = True


# ---------------------------------------------------------------------------
# Low-level HTTP helpers (used only by issue_tag_values custom fan-out)
# ---------------------------------------------------------------------------


def _is_retryable_response(response: Response) -> bool:
    return response.status_code in _RETRYABLE_STATUS_CODES


def _retry_wait_seconds(state: RetryCallState) -> float:
    fallback_wait = min(2 ** (state.attempt_number - 1), 30)
    if state.outcome is None or state.outcome.failed:
        return float(fallback_wait)

    response = state.outcome.result()
    if response.status_code != 429:
        return float(fallback_wait)

    reset_header = response.headers.get("X-Sentry-Rate-Limit-Reset")
    if not reset_header:
        return float(fallback_wait)

    try:
        reset_epoch = int(reset_header)
    except ValueError:
        return float(fallback_wait)

    wait_until_reset = reset_epoch - int(datetime.now(UTC).timestamp())
    if wait_until_reset <= 0:
        return float(fallback_wait)

    return float(wait_until_reset)


def _raise_on_failed_retry(state: RetryCallState) -> Response:
    if state.outcome is None:
        raise RuntimeError("Unexpected request retry state")
    if state.outcome.failed:
        exc = state.outcome.exception()
        if exc is None:
            raise RuntimeError("Unexpected request retry state")
        raise exc
    return state.outcome.result()


@retry(
    stop=stop_after_attempt(_MAX_RETRIES + 1),
    wait=_retry_wait_seconds,
    retry=retry_if_exception_type(RequestException) | retry_if_result(_is_retryable_response),
    retry_error_callback=_raise_on_failed_retry,
)
def _request_with_retry(
    url: str,
    headers: dict[str, str],
    params: dict[str, Any] | None,
    timeout: int = _REQUEST_TIMEOUT,
) -> Response:
    return make_tracked_session().get(url, headers=headers, params=params, timeout=timeout)


def _iter_endpoint_rows(
    base_api_url: str,
    path: str,
    headers: dict[str, str],
    params: dict[str, Any] | None,
    max_pages: int | None = None,
) -> Iterator[dict[str, Any]]:
    url = urljoin(f"{base_api_url}/", path.lstrip("/"))
    current_params: dict[str, Any] | None = params if params is not None else {}
    pages_read = 0
    max_pages_to_read = max_pages if max_pages and max_pages > 0 else None

    while url:
        if max_pages_to_read is not None and pages_read >= max_pages_to_read:
            if max_pages_to_read == _MAX_PAGES_PER_PARENT:
                logger.info(
                    "sentry_source.max_pages_per_parent_reached",
                    resource_path=path,
                    max_pages_per_parent=_MAX_PAGES_PER_PARENT,
                )
            break

        response = _request_with_retry(url=url, headers=headers, params=current_params)
        response.raise_for_status()

        payload = response.json()
        yield from payload

        pages_read += 1
        next_url = _parse_next_link(response.headers.get("Link", ""))
        if not next_url:
            break
        url = urljoin(f"{base_api_url}/", next_url)
        current_params = None


def _parse_datetime_value(value: Any) -> datetime | None:
    if isinstance(value, str):
        try:
            parsed_value = dateutil_parser.parse(value)
        except (ValueError, TypeError):
            return None
        return coerce_datetime_to_utc(parsed_value)
    return coerce_datetime_to_utc(value)


# ---------------------------------------------------------------------------
# Issue tag-values fan-out (custom iterator — requires two-level fan-out:
# issues → tags-per-issue → values-per-tag.  Can't be expressed as a single
# parent→child dependency in rest_api_resources.)
# ---------------------------------------------------------------------------


def _skip_rows_on_stale_issue_404(
    rows: Iterator[dict[str, Any]], organization_slug: str, issue_id: str, stale_issues: set[str]
) -> Iterator[dict[str, Any]]:
    """Swallow a 404 raised while iterating a warehouse-snapshot issue's sub-resource.

    Records the issue in `stale_issues` so the caller can report how much of the snapshot the
    vendor no longer has — the drift measure the reuse follow-up needs.
    """
    try:
        yield from rows
    except HTTPError as exc:
        response = exc.response
        if response is not None and response.status_code == 404:
            stale_issues.add(issue_id)
            logger.info(
                "sentry_source.stale_warehouse_issue_skipped",
                organization_slug=organization_slug,
                issue_id=issue_id,
            )
            return
        raise


# lastSeen carries the scan floor, so it is always projected. A parent whose column selection
# dropped it fails the eager resolve check and drives this child from the API instead.
_ISSUES_PARENT_COLUMNS = ["id", "lastSeen"]


def _issues_parent_row_filter(cutoff_last_seen: datetime | None) -> ParentRowFilter:
    """Floor for the issues scan: Sentry's list window, tightened by the incremental cutoff.

    The cutoff half is pure I/O: it turns the per-row skip below into a predicate the parquet
    reader applies, so an incremental run stops reading issues it would only discard. The
    per-row check stays the authority, and the floor is never tighter than it.

    The window half caps a watermark older than the window from widening the scan back out.
    The no-watermark case never reaches this filter: `sentry_source` sends full refreshes down
    the API parent path, because Sentry clamps its listing to the org's plan retention and a
    snapshot floor cannot reproduce that bound — see SENTRY_FANOUT_PARENT_WINDOW.
    """
    return dataclasses.replace(ISSUES_PARENT_ROW_FILTER, not_before=cutoff_last_seen)


def _usable_resume_state(
    manager: Optional[ResumableSourceManager[SentryResumeConfig]], parent_version: int | None
) -> Optional[SentryResumeConfig]:
    """The issue_tag_values checkpoint, when this run iterates issues the way it was written.

    A checkpoint is a position in an iteration order, so it only means anything to a run
    walking the same order: the API's `sort=date` listing, or one pinned Delta version.
    Applying one across that boundary fast-forwards past issues the new order never reached
    while the watermark still advances, so the rows are lost until a reset. The full triple
    has to be present — anything partial is treated as absent rather than applied to the
    wrong (issue, tag) pair.

    Callers must also `clear_state()` when this returns None with state still stored: the
    pipeline reads `can_resume()` itself to pick replace-vs-append for chunk 0, so a source
    restarting from the top while that says "resuming" appends a full re-read.
    """
    if manager is None or not manager.can_resume():
        return None
    loaded = manager.load_state()
    if loaded is None or not (loaded.issue_id and loaded.tag_key and loaded.values_next_url):
        return None
    if loaded.parent_version != parent_version:
        return None
    return loaded


def _iter_issue_tag_values_rows(
    base_api_url: str,
    headers: dict[str, str],
    organization_slug: str,
    resumable_source_manager: Optional[ResumableSourceManager[SentryResumeConfig]] = None,
    incremental_last_seen_max: Any = None,
    issues_table: Optional["ParentTableRef"] = None,
    issues_snapshot_at: datetime | None = None,
) -> Iterator[dict[str, Any]]:
    cutoff_last_seen = _parse_datetime_value(incremental_last_seen_max)
    use_warehouse_parent = issues_table is not None

    issues: Iterator[dict[str, Any]]
    if issues_table is not None:
        # noqa reason: keeps deltalake/pyarrow off the import path of this module (imported
        # by the API process for schema discovery) — the reader loads only when syncing.
        from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent import (  # noqa: PLC0415
            iter_parent_pages_from_warehouse,
        )

        # Streamed scan — the reader must never materialize the table. The incremental
        # early-break below becomes a per-row filter in this mode (same issue set, no
        # ordering requirement). Duplicate rows can't occur: append-mode parents take the
        # API path instead of this one.
        issues = (
            row
            for page in iter_parent_pages_from_warehouse(
                table=issues_table,
                parent_name="issues",
                columns=_ISSUES_PARENT_COLUMNS,
                page_size=100,
                schema_name="issue_tag_values",
                row_filter=_issues_parent_row_filter(cutoff_last_seen),
            )
            for row in page
        )
    else:
        issues = _iter_endpoint_rows(
            base_api_url=base_api_url,
            path=f"/organizations/{organization_slug}/issues/",
            headers=headers,
            params={"limit": 100, "query": "", "sort": "date"},
        )

    # A pinned Delta version enumerates its files in a fixed order, so a warehouse run
    # resumes like an API run — but only against a checkpoint written over the same pin.
    parent_version = issues_table.version if issues_table is not None else None
    resume_issue_id: str | None = None
    resume_tag_key: str | None = None
    resume_values_next_url: str | None = None
    loaded = _usable_resume_state(resumable_source_manager, parent_version)
    if loaded is not None:
        resume_issue_id = loaded.issue_id
        resume_tag_key = loaded.tag_key
        resume_values_next_url = loaded.values_next_url

    stale_issues: set[str] = set()
    skipped_for_resume = 0

    for issue in issues:
        if cutoff_last_seen is not None:
            issue_last_seen = _parse_datetime_value(issue.get("lastSeen"))
            if issue_last_seen is not None and issue_last_seen <= cutoff_last_seen:
                # API mode returns issues sorted by date desc, so the first stale issue ends
                # the scan. The warehouse scan is unordered (streaming, no global sort), so
                # stale issues are filtered per row instead — same selected set either way.
                if use_warehouse_parent:
                    continue
                break

        issue_id = str(issue["id"])

        # Fast-forward until we reach the saved checkpoint issue. We rely on
        # the deterministic sort=date ordering to land back on the same issue.
        # If the checkpoint issue has been deleted we could skip forever, so
        # bound the skip count and fall through to a fresh run when exceeded.
        if resume_issue_id is not None and issue_id != resume_issue_id:
            skipped_for_resume += 1
            if skipped_for_resume > _RESUME_ISSUE_SKIP_LIMIT:
                logger.info(
                    "sentry_source.stale_resume_checkpoint",
                    resume_issue_id=resume_issue_id,
                    skipped=skipped_for_resume,
                )
                resume_issue_id = None
                resume_tag_key = None
                resume_values_next_url = None
                # Fall through: process the current issue and subsequent ones fresh.
            else:
                continue

        # Mark that we've found the checkpoint issue. If the checkpoint tag has
        # since disappeared, we still exit the middle loop with no match — clear
        # outer fast-forward state at the end of this iteration so subsequent
        # issues run fresh instead of being skipped forever.
        matched_checkpoint_issue = resume_issue_id is not None

        tags = _iter_endpoint_rows(
            base_api_url=base_api_url,
            path=f"/organizations/{organization_slug}/issues/{issue_id}/tags/",
            headers=headers,
            params={"limit": 100},
            max_pages=_MAX_PAGES_PER_PARENT,
        )
        if use_warehouse_parent:
            # The warehouse snapshot can contain issues deleted upstream since the issues
            # schema last synced; their tags endpoint 404s. A fresh API parent pull would
            # simply not list them, so skip instead of failing the sync.
            tags = _skip_rows_on_stale_issue_404(tags, organization_slug, issue_id, stale_issues)
        for tag in tags:
            tag_key = tag.get("key") or tag.get("id")
            if not isinstance(tag_key, str) or not tag_key:
                continue

            if resume_issue_id is not None and resume_tag_key is not None and tag_key != resume_tag_key:
                continue

            values_path = f"/organizations/{organization_slug}/issues/{issue_id}/tags/{quote(tag_key, safe='')}/values/"
            if resume_issue_id is not None and resume_values_next_url:
                values_url: str = resume_values_next_url
                values_params: dict[str, Any] | None = None
            else:
                values_url = urljoin(f"{base_api_url}/", values_path.lstrip("/"))
                values_params = {"limit": 100, "sort": "-date"}
            pages_read = 0

            # Clear resume markers so the NEXT (issue, tag) pair runs fresh.
            resume_issue_id = None
            resume_tag_key = None
            resume_values_next_url = None

            while values_url:
                if pages_read >= _MAX_PAGES_PER_PARENT:
                    logger.info(
                        "sentry_source.max_pages_per_parent_reached",
                        resource_path=values_path,
                        organization_slug=organization_slug,
                        issue_id=issue_id,
                        tag_key=tag_key,
                        max_pages_per_parent=_MAX_PAGES_PER_PARENT,
                    )
                    break

                response = _request_with_retry(url=values_url, headers=headers, params=values_params)
                try:
                    response.raise_for_status()
                except HTTPError:
                    # Sentry intermittently returns a persistent 5xx for a single
                    # (issue, tag) values endpoint — seen on tags with unusual
                    # keys/values. Retries are already exhausted by
                    # _request_with_retry, so skip this tag's remaining values
                    # rather than failing the whole sync.
                    if response.status_code >= 500:
                        logger.warning(
                            "sentry_source.issue_tag_values_server_error_skipped",
                            organization_slug=organization_slug,
                            issue_id=issue_id,
                            tag_key=tag_key,
                            status_code=response.status_code,
                        )
                        break
                    # Sentry gates individual tag values endpoints at the org level
                    # (data-scrubbing/privacy settings, restricted tags), returning
                    # 403 even for tokens that just listed the issue's tags. Skip the
                    # tag rather than failing the sync — a genuine scope problem would
                    # already have surfaced on the issues/tags listing above.
                    if response.status_code == 403:
                        logger.warning(
                            "sentry_source.issue_tag_values_forbidden_skipped",
                            organization_slug=organization_slug,
                            issue_id=issue_id,
                            tag_key=tag_key,
                            status_code=response.status_code,
                        )
                        break
                    # Warehouse-snapshot parents can be deleted upstream mid-list; their
                    # values endpoint 404s. Skip the tag, same as the stale-issue skip above.
                    if use_warehouse_parent and response.status_code == 404:
                        stale_issues.add(issue_id)
                        logger.info(
                            "sentry_source.stale_warehouse_issue_skipped",
                            organization_slug=organization_slug,
                            issue_id=issue_id,
                            tag_key=tag_key,
                        )
                        break
                    # Other client errors (401, etc.) still propagate to the job-level handler.
                    raise

                try:
                    rows = response.json()
                except JSONDecodeError:
                    # Sentry occasionally returns a 2xx with an empty/unparseable
                    # body for a single (issue, tag) values page. Skip this tag's
                    # remaining values rather than crashing the whole sync — same
                    # graceful-skip as the persistent 5xx case above.
                    logger.warning(
                        "sentry_source.issue_tag_values_invalid_json_skipped",
                        organization_slug=organization_slug,
                        issue_id=issue_id,
                        tag_key=tag_key,
                        status_code=response.status_code,
                    )
                    break

                should_stop = False
                for row in rows:
                    row_last_seen = _parse_datetime_value(row.get("lastSeen"))
                    if cutoff_last_seen is not None and row_last_seen is not None:
                        if row_last_seen <= cutoff_last_seen:
                            should_stop = True
                            break
                    if issues_snapshot_at is not None and row_last_seen is not None:
                        if row_last_seen > issues_snapshot_at:
                            # Newer than the issues snapshot this run fanned out over. Values are
                            # returned newest-first, so skip past it rather than stopping.
                            continue

                    row["issue_id"] = issue_id
                    row["tag_key"] = tag_key
                    yield row

                pages_read += 1
                if should_stop:
                    break

                next_url = _parse_next_link(response.headers.get("Link", ""))

                # Checkpoint the URL of the NEXT values page — it has not been
                # fetched yet, so resume can pick it up directly without
                # re-processing any rows that were already yielded. `parent_version`
                # stamps which issue ordering the position belongs to, so a later
                # attempt reading a different parent ignores it (see
                # `_usable_resume_state`).
                if next_url and resumable_source_manager is not None:
                    resumable_source_manager.save_state(
                        SentryResumeConfig(
                            issue_id=issue_id,
                            tag_key=tag_key,
                            values_next_url=urljoin(f"{base_api_url}/", next_url),
                            parent_version=parent_version,
                        )
                    )

                if not next_url:
                    break
                values_url = urljoin(f"{base_api_url}/", next_url)
                values_params = None

        if matched_checkpoint_issue:
            resume_issue_id = None
            resume_tag_key = None
            resume_values_next_url = None

    if use_warehouse_parent:
        # Stale issues are ones the snapshot still lists but Sentry has dropped, each costing
        # a wasted request per sync. Against the reader's row count this is the drift measure
        # for deciding whether the snapshot needs a freshness filter — see the plan follow-up.
        logger.info(
            "sentry_source.warehouse_parent_stale_issues",
            organization_slug=organization_slug,
            stale_issues=len(stale_issues),
        )


# ---------------------------------------------------------------------------
# Endpoints whose payload needs reshaping before it can be a table
# ---------------------------------------------------------------------------

# Sentry answers a request for a product surface the organization doesn't have with a
# 400, so an unavailable trace item dataset is indistinguishable from a rejected param.
_UNAVAILABLE_DATASET_STATUSES = (400, 403, 404)
# Per-project surfaces only ever go missing through permissions or an absent config.
_MISSING_PROJECT_RESOURCE_STATUSES = (403, 404)
# Sentry's stats-summary endpoint 400s with this detail when the token's user has no
# project membership in the org, even though the token itself is otherwise valid.
_NO_PROJECTS_AVAILABLE_DETAIL = "No projects available"

# Any other 400 from the stats-summary endpoint is a deterministic rejection of the request we
# build (most often the requested window falling outside the org's plan retention), so retrying
# replays it identically. Surface a credential-safe message the source classifies as non-retryable
# (see `SentrySource.get_non_retryable_errors`) instead of burning retries on the raw HTTPError,
# whose URL embeds the org slug. The wording never interpolates the org, URL, or response body.
STATS_SUMMARY_REJECTED_MESSAGE = (
    "Sentry rejected PostHog's request for your per-project usage stats (the "
    "organization_stats_summary table) with an HTTP 400. This usually means the requested date "
    "range is outside your Sentry plan's data retention. Remove that table from this source's "
    "selected tables, then re-enable the sync."
)


class SentryStatsSummaryRejectedError(Exception):
    """The stats-summary endpoint rejected our request with a non-recoverable 400."""


def _iter_rows_tolerating_unavailable(
    rows: Iterator[dict[str, Any]],
    endpoint: str,
    skippable_statuses: tuple[int, ...],
    **log_context: Any,
) -> Iterator[dict[str, Any]]:
    """Yield rows, treating the given statuses as "this slice isn't available here".

    Several of the newer product surfaces are gated per organization or per project, so
    one unavailable slice must not fail the whole table.
    """
    try:
        yield from rows
    except HTTPError as exc:
        response = exc.response
        if response is not None and response.status_code in skippable_statuses:
            logger.warning(
                "sentry_source.endpoint_slice_unavailable_skipped",
                endpoint=endpoint,
                status_code=response.status_code,
                **log_context,
            )
            return
        raise


def _series_value(series: Any, index: int) -> Any:
    if not isinstance(series, list) or index >= len(series):
        return None
    return series[index]


def _group_key(by: dict[str, Any], key: str) -> str:
    value = by.get(key)
    # Grouped dimensions land in the primary key, and Delta merges never match on a
    # null, so an absent dimension becomes an empty string rather than None.
    return "" if value is None else str(value)


def _endpoint_path(endpoint: str, **values: str) -> str:
    """Resolve an endpoint's configured path so `settings.py` stays the only place paths live."""
    return SENTRY_ENDPOINTS[endpoint].path.format(**values)


def _fetch_json(base_api_url: str, path: str, headers: dict[str, str], params: dict[str, Any]) -> Any:
    url = urljoin(f"{base_api_url}/", path.lstrip("/"))
    response = _request_with_retry(url=url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()


def _iter_sessions_rows(
    base_api_url: str,
    headers: dict[str, str],
    organization_slug: str,
    incremental_value: Any = None,
) -> Iterator[dict[str, Any]]:
    """Release health sessions, flattened to one row per interval per group."""
    window = _retention_window(incremental_value)
    payload = _fetch_json(
        base_api_url,
        _endpoint_path("sessions", organization_slug=organization_slug),
        headers,
        {
            "field": ["sum(session)", "count_unique(user)"],
            "groupBy": ["project", "release", "environment", "session.status"],
            "interval": "1d",
            "start": window.start,
            "end": window.end,
        },
    )

    intervals = payload.get("intervals") or []
    for group in payload.get("groups") or []:
        by = group.get("by") or {}
        series = group.get("series") or {}
        for index, interval_start in enumerate(intervals):
            yield {
                "interval_start": interval_start,
                "project": _group_key(by, "project"),
                "release": _group_key(by, "release"),
                "environment": _group_key(by, "environment"),
                "session_status": _group_key(by, "session.status"),
                "sum_session": _series_value(series.get("sum(session)"), index),
                "count_unique_user": _series_value(series.get("count_unique(user)"), index),
            }


def _iter_organization_stats_rows(
    base_api_url: str,
    headers: dict[str, str],
    organization_slug: str,
    incremental_value: Any = None,
) -> Iterator[dict[str, Any]]:
    """Org-wide accepted/dropped event volume, flattened to one row per interval per group.

    ``project`` is deliberately not in ``groupBy``: Sentry collapses the series into a
    single period total when it is, which would make the interval column meaningless.
    Per-project volume lives in ``organization_stats_summary``.
    """
    window = _retention_window(incremental_value)
    payload = _fetch_json(
        base_api_url,
        _endpoint_path("organization_stats", organization_slug=organization_slug),
        headers,
        {
            "field": "sum(quantity)",
            "groupBy": ["outcome", "category", "reason"],
            "interval": "1d",
            "start": window.start,
            "end": window.end,
        },
    )

    intervals = payload.get("intervals") or []
    for group in payload.get("groups") or []:
        by = group.get("by") or {}
        series = group.get("series") or {}
        for index, interval_start in enumerate(intervals):
            yield {
                "interval_start": interval_start,
                "outcome": _group_key(by, "outcome"),
                "category": _group_key(by, "category"),
                "reason": _group_key(by, "reason"),
                "quantity": _series_value(series.get("sum(quantity)"), index),
            }


def _iter_organization_stats_summary_rows(
    base_api_url: str,
    headers: dict[str, str],
    organization_slug: str,
) -> Iterator[dict[str, Any]]:
    """Per-project event volume for the retention window, one row per project per category."""
    # A relative statsPeriod of the full retention length lands on the retention boundary, which
    # Sentry rejects with a 400. Send an explicit clamped window instead, matching the other stats
    # endpoints (see organization_stats).
    window = _retention_window()
    try:
        payload = _fetch_json(
            base_api_url,
            _endpoint_path("organization_stats_summary", organization_slug=organization_slug),
            headers,
            {"field": "sum(quantity)", "start": window.start, "end": window.end},
        )
    except HTTPError as exc:
        response = exc.response
        if response is not None and response.status_code == 400:
            try:
                detail = response.json().get("detail")
            except JSONDecodeError:
                detail = None
            if detail == _NO_PROJECTS_AVAILABLE_DETAIL:
                # The requesting token's user isn't a member of any project in this
                # org — Sentry rejects that as a 400 rather than an empty result.
                # Skip the table rather than failing the whole sync.
                logger.warning(
                    "sentry_source.organization_stats_summary_no_projects_skipped",
                    organization_slug=organization_slug,
                )
                return
            raise SentryStatsSummaryRejectedError(STATS_SUMMARY_REJECTED_MESSAGE) from exc
        raise

    period_start = payload.get("start")
    period_end = payload.get("end")
    for project in payload.get("projects") or []:
        for stats in project.get("stats") or []:
            totals = stats.get("totals") or {}
            yield {
                "project_id": project.get("id"),
                "project_slug": project.get("slug"),
                "category": stats.get("category"),
                "outcomes": stats.get("outcomes"),
                # Lifted out of `totals` so the column names survive normalization —
                # `sum(quantity)` would otherwise land as an unreadable nested key.
                "quantity": totals.get("sum(quantity)"),
                "dropped": totals.get("dropped"),
                "period_start": period_start,
                "period_end": period_end,
            }


def _iter_trace_item_attributes_rows(
    base_api_url: str,
    headers: dict[str, str],
    organization_slug: str,
) -> Iterator[dict[str, Any]]:
    """Attribute keys available on each trace item dataset (spans, logs, ...)."""
    for dataset in TRACE_ITEM_DATASETS:
        rows = _iter_endpoint_rows(
            base_api_url=base_api_url,
            path=_endpoint_path("trace_item_attributes", organization_slug=organization_slug),
            headers=headers,
            params={"dataset": dataset},
            max_pages=_MAX_PAGES_PER_PARENT,
        )
        for row in _iter_rows_tolerating_unavailable(
            rows, "trace_item_attributes", _UNAVAILABLE_DATASET_STATUSES, dataset=dataset
        ):
            row["dataset"] = dataset
            yield row


def _iter_trace_item_stats_rows(
    base_api_url: str,
    headers: dict[str, str],
    organization_slug: str,
) -> Iterator[dict[str, Any]]:
    """Attribute value distributions over trace items, flattened to one row per label."""

    def _distributions(item_type: str) -> Iterator[dict[str, Any]]:
        payload = _fetch_json(
            base_api_url,
            _endpoint_path("trace_item_stats", organization_slug=organization_slug),
            headers,
            {"statsType": "attributeDistributions", "itemType": item_type},
        )
        for entry in payload.get("data") or []:
            distributions = (entry.get("attributeDistributions") or {}).get("data") or {}
            for attribute, buckets in distributions.items():
                for bucket in buckets or []:
                    yield {
                        "item_type": item_type,
                        "attribute": attribute,
                        "label": bucket.get("label"),
                        "value": bucket.get("value"),
                    }

    for item_type in TRACE_ITEM_STATS_TYPES:
        yield from _iter_rows_tolerating_unavailable(
            _distributions(item_type), "trace_item_stats", _UNAVAILABLE_DATASET_STATUSES, item_type=item_type
        )


def _iter_projects(base_api_url: str, headers: dict[str, str], organization_slug: str) -> Iterator[dict[str, Any]]:
    return _iter_endpoint_rows(
        base_api_url=base_api_url,
        path=_endpoint_path("projects", organization_slug=organization_slug),
        headers=headers,
        params={"limit": 100},
    )


def _iter_project_ownership_rows(
    base_api_url: str,
    headers: dict[str, str],
    organization_slug: str,
) -> Iterator[dict[str, Any]]:
    """Issue-owner rules, one row per project (the endpoint returns a single object)."""

    def _ownership(project_slug: str) -> Iterator[dict[str, Any]]:
        payload = _fetch_json(
            base_api_url,
            _endpoint_path(
                "project_ownership",
                organization_slug=organization_slug,
                project_slug=quote(project_slug, safe=""),
            ),
            headers,
            {},
        )
        if isinstance(payload, dict):
            yield payload

    for project in _iter_projects(base_api_url, headers, organization_slug):
        project_slug = project.get("slug")
        if not isinstance(project_slug, str) or not project_slug:
            continue
        for row in _iter_rows_tolerating_unavailable(
            _ownership(project_slug),
            "project_ownership",
            _MISSING_PROJECT_RESOURCE_STATUSES,
            project_slug=project_slug,
        ):
            row["project_id"] = project.get("id")
            row["project_slug"] = project_slug
            yield row


def _epoch_seconds(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    parsed = _parse_datetime_value(value)
    if parsed is not None:
        return int(parsed.timestamp())
    return None


def _iter_project_stats_rows(
    base_api_url: str,
    headers: dict[str, str],
    organization_slug: str,
    incremental_value: Any = None,
) -> Iterator[dict[str, Any]]:
    """Per-project event counts, flattened from Sentry's [timestamp, value] point pairs."""
    now = datetime.now(UTC)
    floor = int(_retention_floor(now).timestamp())
    requested_since = _epoch_seconds(incremental_value)
    since = floor if requested_since is None else min(max(requested_since, floor), int(now.timestamp()))
    until = int(now.timestamp())

    def _points(project_slug: str, stat: str) -> Iterator[dict[str, Any]]:
        payload = _fetch_json(
            base_api_url,
            _endpoint_path(
                "project_stats",
                organization_slug=organization_slug,
                project_slug=quote(project_slug, safe=""),
            ),
            headers,
            {"stat": stat, "resolution": "1d", "since": since, "until": until},
        )
        for point in payload or []:
            if not isinstance(point, list) or len(point) < 2:
                continue
            yield {"stat": stat, "timestamp": point[0], "value": point[1]}

    for project in _iter_projects(base_api_url, headers, organization_slug):
        project_slug = project.get("slug")
        if not isinstance(project_slug, str) or not project_slug:
            continue
        for stat in PROJECT_STAT_NAMES:
            for row in _iter_rows_tolerating_unavailable(
                _points(project_slug, stat),
                "project_stats",
                _MISSING_PROJECT_RESOURCE_STATUSES,
                project_slug=project_slug,
                stat=stat,
            ):
                row["project_id"] = project.get("id")
                row["project_slug"] = project_slug
                yield row


def _custom_endpoint_rows(
    endpoint: str,
    base_api_url: str,
    headers: dict[str, str],
    organization_slug: str,
    incremental_value: Any = None,
) -> Iterator[dict[str, Any]]:
    if endpoint == "sessions":
        return _iter_sessions_rows(base_api_url, headers, organization_slug, incremental_value)
    if endpoint == "organization_stats":
        return _iter_organization_stats_rows(base_api_url, headers, organization_slug, incremental_value)
    if endpoint == "organization_stats_summary":
        return _iter_organization_stats_summary_rows(base_api_url, headers, organization_slug)
    if endpoint == "trace_item_attributes":
        return _iter_trace_item_attributes_rows(base_api_url, headers, organization_slug)
    if endpoint == "trace_item_stats":
        return _iter_trace_item_stats_rows(base_api_url, headers, organization_slug)
    if endpoint == "project_ownership":
        return _iter_project_ownership_rows(base_api_url, headers, organization_slug)
    if endpoint == "project_stats":
        return _iter_project_stats_rows(base_api_url, headers, organization_slug, incremental_value)
    raise ValueError(f"No custom iterator registered for endpoint '{endpoint}'")


# ---------------------------------------------------------------------------
# Credential validation
# ---------------------------------------------------------------------------


def validate_credentials(
    auth_token: str,
    organization_slug: str,
    api_base_url: str | None = None,
) -> tuple[bool, str | None]:
    try:
        base_url = _validated_api_base_url(api_base_url)
    except ValueError as exc:
        return False, str(exc)

    url = f"{base_url}/api/0/organizations/{organization_slug}/projects/"
    headers = _auth_headers(auth_token)

    try:
        response = make_tracked_session().get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return True, None
        if response.status_code == 401:
            return False, "Invalid Sentry auth token. Please update your token and reconnect."
        if response.status_code == 403:
            return (
                False,
                "Sentry token is missing required scopes. Create a token with these scopes and reconnect: "
                + ", ".join(REQUIRED_SENTRY_SCOPES)
                + ".",
            )
        if response.status_code == 404:
            return False, "Sentry organization not found. Verify your organization slug, then reconnect."

        # Keep the vendor detail in logs for debugging, but never surface it — the raw body can
        # echo the org slug or unrelated Sentry internals back to the customer.
        logger.warning("sentry_source.validate_credentials_unexpected_status", status_code=response.status_code)
        return False, "Could not connect to Sentry. Check your auth token and organization slug, then reconnect."
    except RequestException as exc:
        logger.warning("sentry_source.validate_credentials_request_error", error=str(exc))
        return False, "Could not reach Sentry to validate your credentials. Check your connection, then try again."


# ---------------------------------------------------------------------------
# Resource config builder (org-level flat endpoints only)
# ---------------------------------------------------------------------------


def get_resource(
    endpoint: str,
    organization_slug: str,
    should_use_incremental_field: bool,
    incremental_field: str | None = None,
) -> EndpointResource:
    config = SENTRY_ENDPOINTS[endpoint]
    if config.fanout or config.custom_iterator:
        raise ValueError(f"Fan-out endpoint '{endpoint}' must use the fan-out path")

    params: dict[str, Any] = {}
    if config.page_size_param:
        params[config.page_size_param] = config.page_size
    params.update(config.params)

    endpoint_config: Endpoint = {
        "path": config.path.format(organization_slug=organization_slug),
        "params": params,
    }
    if config.data_selector:
        endpoint_config["data_selector"] = config.data_selector

    if endpoint == "issues":
        params["query"] = ""
        params["sort"] = "date" if (incremental_field or config.default_incremental_field) == "lastSeen" else "new"
        if should_use_incremental_field and config.incremental_fields:
            endpoint_config["incremental"] = _sentry_incremental_window(
                incremental_field or config.default_incremental_field or "lastSeen"
            )
    elif should_use_incremental_field and config.incremental_fields:
        window_factory = (
            _sentry_retention_incremental_window if config.retention_bounded else _sentry_incremental_window
        )
        endpoint_config["incremental"] = window_factory(
            incremental_field or config.default_incremental_field or "dateCreated"
        )

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field and config.incremental_fields
        else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _skip_endpoint_on_forbidden(resource: Iterable[Any], endpoint: str) -> Iterator[Any]:
    """Yield pages from a fan-out resource, treating a 403 as "endpoint not
    available for this organization" and stopping gracefully.

    Sentry's project service hooks API is gated at the organization level, so it
    returns 403 Forbidden even for tokens that already hold full project/admin
    scopes. Letting that 403 propagate marks the whole schema as a non-retryable
    failure (see ``SentrySource.get_non_retryable_errors``), permanently erroring
    a source whose credentials are otherwise valid. Skipping the endpoint instead
    lets the sync complete with an empty table — the same graceful-skip approach
    used for persistent server errors in ``_iter_issue_tag_values_rows``. Genuine
    scope problems still surface on the other (non-skipped) endpoints.
    """
    try:
        yield from resource
    except HTTPError as exc:
        response = exc.response
        if response is not None and response.status_code == 403:
            logger.warning(
                "sentry_source.endpoint_forbidden_skipped",
                endpoint=endpoint,
                status_code=response.status_code,
            )
            return
        raise


def _make_source_response(endpoint_config: SentryEndpointConfig, items_fn) -> SourceResponse:
    return SourceResponse(
        name=endpoint_config.name,
        items=items_fn,
        primary_keys=endpoint_config.primary_key
        if isinstance(endpoint_config.primary_key, list)
        else [endpoint_config.primary_key],
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


# ---------------------------------------------------------------------------
# Main entry point — routes each endpoint to the right extraction strategy
# ---------------------------------------------------------------------------


def sentry_source(
    auth_token: str,
    organization_slug: str,
    api_base_url: str | None,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: Optional[ResumableSourceManager[SentryResumeConfig]] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
    source_id: str | None = None,
    use_warehouse_parent: bool = False,
) -> SourceResponse:
    endpoint_config = SENTRY_ENDPOINTS[endpoint]
    normalized_base_url = _validated_api_base_url(api_base_url)
    base_api_url = f"{normalized_base_url}/api/0"

    # issue_tag_values needs two-level fan-out (issues → tags → values)
    # which can't be expressed as a single parent→child dependency.
    if endpoint == "issue_tag_values":
        headers = _auth_headers(auth_token)
        incremental_last_seen_max = db_incremental_field_last_value if should_use_incremental_field else None
        issues_table: ParentTableRef | None = None
        issues_snapshot_at: datetime | None = None
        # Warehouse reuse only with a watermark: the per-row cutoff then bounds the fan-out to
        # issues newer than the last run, the regime whose volume matched the API path in
        # production. Without one (a full refresh), the only available floor is our window
        # constant, and Sentry clamps its own listing to the org plan retention below it --
        # see SENTRY_FANOUT_PARENT_WINDOW -- so the API path is the only faithful parent.
        if use_warehouse_parent and _parse_datetime_value(incremental_last_seen_max) is not None:
            if team_id is None or not source_id:
                raise ValueError("team_id and source_id are required when reading the issues parent from the warehouse")
            # noqa reason: keeps deltalake/pyarrow off the import path of this module (imported
            # by the API process for schema discovery) — the reader stack loads only when syncing.
            from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent import (  # noqa: PLC0415
                parent_snapshot_covers_through,
                try_resolve_parent_table,
            )

            # How far the issues snapshot is guaranteed complete. The tag values fanned out below
            # are fetched live, so emitting one past this point would carry the watermark over
            # issues the snapshot has not shown yet, and the next floor would skip them for good.
            # Read before the table is pinned, never after: a sync completing between the two
            # reads would otherwise cap on the newer job while the fan-out reads the older
            # snapshot. No completed sync means nothing to cap against, so take the API path.
            issues_snapshot_at = parent_snapshot_covers_through(team_id, source_id, "issues")
            if issues_snapshot_at is not None:
                # Resolved here, in sync source-build context, never inside the iterator: its body
                # runs on the pipeline's executor threads, where ad-hoc ORM reads hit the
                # pooler-drop failure mode resolve_parent_table_ref documents.
                issues_table = try_resolve_parent_table(
                    team_id=team_id,
                    source_id=source_id,
                    parent_name="issues",
                    required_columns=_ISSUES_PARENT_COLUMNS,
                    schema_name="issue_tag_values",
                    row_filter=_issues_parent_row_filter(_parse_datetime_value(incremental_last_seen_max)),
                )
                if issues_table is None:
                    # The table turned out to be unreadable, so this run reads the live issues
                    # API. That listing has no snapshot behind it, so capping against one would
                    # drop fresh tag values the API path had no reason to hold back.
                    issues_snapshot_at = None
        if resumable_source_manager is not None and resumable_source_manager.can_resume():
            # The pipeline reads this same Redis state to pick replace-vs-append for chunk 0,
            # so state the iterator will refuse has to go now, before it decides. Same
            # predicate as the iterator's, so the two can't disagree.
            if _usable_resume_state(resumable_source_manager, issues_table.version if issues_table else None) is None:
                resumable_source_manager.clear_state()
        return _make_source_response(
            endpoint_config,
            lambda: _iter_issue_tag_values_rows(
                base_api_url=base_api_url,
                headers=headers,
                organization_slug=organization_slug,
                resumable_source_manager=resumable_source_manager,
                incremental_last_seen_max=incremental_last_seen_max,
                issues_table=issues_table,
                issues_snapshot_at=issues_snapshot_at,
            ),
        )

    # Endpoints whose payload isn't a paginated row list (time series, per-project
    # singletons) are reshaped by a bespoke iterator instead.
    if endpoint_config.custom_iterator:
        headers = _auth_headers(auth_token)
        return _make_source_response(
            endpoint_config,
            lambda: _custom_endpoint_rows(
                endpoint=endpoint,
                base_api_url=base_api_url,
                headers=headers,
                organization_slug=organization_slug,
                incremental_value=db_incremental_field_last_value if should_use_incremental_field else None,
            ),
        )

    # --- Generic parent->child fan-out ---
    # Dependent resources don't currently support resume in the rest_source
    # framework; the manager is intentionally not threaded into this path.
    if endpoint_config.fanout:
        dependent_resource = cast(
            Iterable[Any],
            build_dependent_resource(
                endpoint_configs=SENTRY_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=endpoint_config.fanout,
                client_config=_rest_api_client_config(base_api_url, auth_token),
                path_format_values={"organization_slug": organization_slug},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
                incremental_field=incremental_field,
                incremental_config_factory=_sentry_incremental_window,
                source_id=source_id,
                use_warehouse_parent=use_warehouse_parent,
                page_size_param=endpoint_config.page_size_param,
            ),
        )
        # Sentry gates the service hooks API at the org level, so it 403s even
        # for fully-scoped tokens. Skip it gracefully rather than permanently
        # erroring the schema (which the non-retryable 403 handling would do).
        if endpoint == "project_service_hooks":
            return _make_source_response(
                endpoint_config, lambda: _skip_endpoint_on_forbidden(dependent_resource, endpoint)
            )
        return _make_source_response(endpoint_config, lambda: dependent_resource)

    # --- Flat org-level endpoints (via rest_api_resources) ---
    config: RESTAPIConfig = {
        "client": _rest_api_client_config(base_api_url, auth_token),
        "resource_defaults": {
            "write_disposition": "replace",
            "endpoint": {"params": {endpoint_config.page_size_param: endpoint_config.page_size}}
            if endpoint_config.page_size_param
            else {},
        },
        "resources": [
            get_resource(
                endpoint=endpoint,
                organization_slug=organization_slug,
                should_use_incremental_field=should_use_incremental_field,
                incremental_field=incremental_field,
            )
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    resume_hook: Optional[Callable[[Optional[dict[str, Any]]], None]] = None
    if resumable_source_manager is not None:
        if resumable_source_manager.can_resume():
            resume_config = resumable_source_manager.load_state()
            if resume_config is not None and resume_config.next_url:
                initial_paginator_state = {"next_url": resume_config.next_url}

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Match klaviyo/reddit_ads: persist only while there is another
            # page to resume to. Redis TTL cleans up on completion.
            if state and state.get("next_url") and resumable_source_manager is not None:
                resumable_source_manager.save_state(SentryResumeConfig(next_url=state["next_url"]))

        resume_hook = save_checkpoint

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=resume_hook,
        initial_paginator_state=initial_paginator_state,
    )
    return _make_source_response(endpoint_config, lambda: resource)
