import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.bitrise.settings import BITRISE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

BITRISE_BASE_URL = "https://api.bitrise.io/v0.1"
# Bitrise list endpoints cap `limit` at 50.
PAGE_LIMIT = 50
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5
# Safety overlap subtracted from the incremental watermark: builds that were still running (or on
# hold) at the last sync keep mutating (status, finished_at) after their trigger time, so each run
# re-pulls a trailing window and merge dedupes the re-fetched rows on the primary key.
INCREMENTAL_LOOKBACK = timedelta(hours=24)


class BitriseRetryableError(Exception):
    pass


Fetcher = Callable[[str, dict[str, Any]], dict[str, Any]]


@dataclasses.dataclass
class BitriseResumeConfig:
    # Fan-out bookmark: the app currently being processed. A stable slug (not a positional index)
    # so apps added/removed between a crash and the retry can't resume us into the wrong app.
    # None for the top-level apps endpoint.
    app_slug: str | None = None
    # `next` paging anchor within the current listing. None means "start at the first page".
    next: str | None = None


def _get_session(api_token: str) -> requests.Session:
    # Bitrise expects the raw token in the Authorization header (no Bearer prefix).
    return make_tracked_session(headers={"Authorization": api_token}, redact_values=(api_token,))


def _to_unix_timestamp(value: Any) -> int | None:
    """Convert an incremental cursor to the Unix timestamp Bitrise's `after` filter expects."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
        except ValueError:
            return None
    return None


def _build_after_param(should_use_incremental_field: bool, db_incremental_field_last_value: Any) -> int | None:
    if not should_use_incremental_field or db_incremental_field_last_value is None:
        return None
    timestamp = _to_unix_timestamp(db_incremental_field_last_value)
    if timestamp is None:
        return None
    return max(0, timestamp - int(INCREMENTAL_LOOKBACK.total_seconds()))


def validate_credentials(api_token: str) -> bool:
    """Confirm the token is genuine with a cheap probe.

    Personal access tokens can call /me; workspace API tokens are workspace-scoped and may not,
    so fall back to a one-app listing before declaring the token invalid.
    """
    session = _get_session(api_token)
    try:
        response = session.get(f"{BITRISE_BASE_URL}/me", timeout=10)
        if response.status_code == 200:
            return True
        response = session.get(f"{BITRISE_BASE_URL}/apps?{urlencode({'limit': 1})}", timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _make_fetcher(session: requests.Session, logger: FilteringBoundLogger) -> Fetcher:
    @retry(
        retry=retry_if_exception_type(
            (
                BitriseRetryableError,
                requests.ReadTimeout,
                requests.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            )
        ),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=60),
        reraise=True,
    )
    def fetch(path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{BITRISE_BASE_URL}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

        # Bitrise rate-limits per account and returns 429; back off exponentially.
        if response.status_code == 429 or response.status_code >= 500:
            raise BitriseRetryableError(f"Bitrise API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            # 404 is expected during fan-out (an app or build deleted mid-sync) and handled by callers.
            log = logger.warning if response.status_code == 404 else logger.error
            log(f"Bitrise API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    return fetch


def _iter_pages(
    fetch: Fetcher,
    path: str,
    params: dict[str, Any],
    start_next: str | None = None,
) -> Iterator[tuple[list[Any], str | None]]:
    """Walk a Bitrise cursor-paginated listing, yielding (items, next_anchor) per page.

    Bitrise signals more pages with a `paging.next` anchor value passed back as `?next=`;
    the anchor is absent on the final page.
    """
    next_anchor = start_next
    while True:
        page_params = dict(params)
        if next_anchor:
            page_params["next"] = next_anchor
        data = fetch(path, page_params)
        items = data.get("data") or []
        next_anchor = (data.get("paging") or {}).get("next")
        yield items, next_anchor
        if not next_anchor:
            return


def _list_app_slugs(fetch: Fetcher) -> list[str]:
    return [app["slug"] for items, _ in _iter_pages(fetch, "/apps", {"limit": PAGE_LIMIT}) for app in items]


def _resolve_fan_out_resume(
    app_slugs: list[str],
    resumable_source_manager: ResumableSourceManager[BitriseResumeConfig],
    logger: FilteringBoundLogger,
) -> tuple[list[str], str | None]:
    """Slice the app list down to what a crashed attempt still owes.

    If the bookmarked app no longer exists (deleted between runs), start over from the first app;
    merge dedupes any re-pulled rows on the primary key.
    """
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.app_slug is not None and resume.app_slug in app_slugs:
        logger.debug(f"Bitrise: resuming from app_slug={resume.app_slug}, next={resume.next}")
        return app_slugs[app_slugs.index(resume.app_slug) :], resume.next
    return app_slugs, None


def _get_apps_rows(
    fetch: Fetcher,
    resumable_source_manager: ResumableSourceManager[BitriseResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_next = resume.next if resume else None

    for items, next_anchor in _iter_pages(fetch, "/apps", {"limit": PAGE_LIMIT}, start_next):
        if items:
            yield items
        # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last
        # page rather than skipping it — merge dedupes on the primary key.
        if next_anchor:
            resumable_source_manager.save_state(BitriseResumeConfig(next=next_anchor))


def _get_builds_rows(
    fetch: Fetcher,
    resumable_source_manager: ResumableSourceManager[BitriseResumeConfig],
    logger: FilteringBoundLogger,
    after: int | None,
) -> Iterator[list[dict[str, Any]]]:
    app_slugs = _list_app_slugs(fetch)
    remaining, resume_next = _resolve_fan_out_resume(app_slugs, resumable_source_manager, logger)

    params: dict[str, Any] = {"limit": PAGE_LIMIT, "sort_by": "created_at"}
    if after is not None:
        params["after"] = after

    for index, app_slug in enumerate(remaining):
        start_next = resume_next
        resume_next = None  # only the resumed-into app uses the saved anchor; the rest start fresh

        try:
            for items, next_anchor in _iter_pages(fetch, f"/apps/{quote(app_slug)}/builds", params, start_next):
                rows = [{**build, "app_slug": app_slug} for build in items]
                if rows:
                    yield rows
                if next_anchor:
                    resumable_source_manager.save_state(BitriseResumeConfig(app_slug=app_slug, next=next_anchor))
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Bitrise: app {app_slug} not found while fetching builds, skipping")
            else:
                raise

        if index + 1 < len(remaining):
            resumable_source_manager.save_state(BitriseResumeConfig(app_slug=remaining[index + 1], next=None))


def _get_workflows_rows(
    fetch: Fetcher,
    resumable_source_manager: ResumableSourceManager[BitriseResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    app_slugs = _list_app_slugs(fetch)
    remaining, _ = _resolve_fan_out_resume(app_slugs, resumable_source_manager, logger)

    for index, app_slug in enumerate(remaining):
        try:
            # build-workflows returns bare workflow name strings, not objects; no pagination.
            data = fetch(f"/apps/{quote(app_slug)}/build-workflows", {})
            rows = [{"app_slug": app_slug, "workflow": name} for name in data.get("data") or []]
            if rows:
                yield rows
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Bitrise: app {app_slug} not found while fetching workflows, skipping")
            else:
                raise

        if index + 1 < len(remaining):
            resumable_source_manager.save_state(BitriseResumeConfig(app_slug=remaining[index + 1], next=None))


def _get_artifacts_rows(
    fetch: Fetcher,
    resumable_source_manager: ResumableSourceManager[BitriseResumeConfig],
    logger: FilteringBoundLogger,
    after: int | None,
) -> Iterator[list[dict[str, Any]]]:
    """Two-level fan-out: apps -> builds -> per-build artifact listings.

    The incremental filter applies at the parent builds level (`after` on trigger time), and each
    artifact row carries `build_triggered_at` so the pipeline can watermark on it. Resume state is
    kept at app granularity only: a resumed attempt restarts the bookmarked app's builds and merge
    dedupes the re-pulled artifacts.
    """
    app_slugs = _list_app_slugs(fetch)
    remaining, _ = _resolve_fan_out_resume(app_slugs, resumable_source_manager, logger)

    build_params: dict[str, Any] = {"limit": PAGE_LIMIT, "sort_by": "created_at"}
    if after is not None:
        build_params["after"] = after

    for index, app_slug in enumerate(remaining):
        try:
            for build_items, _ in _iter_pages(fetch, f"/apps/{quote(app_slug)}/builds", build_params):
                for build in build_items:
                    build_slug = build["slug"]
                    for items, _ in _iter_pages(
                        fetch, f"/apps/{quote(app_slug)}/builds/{quote(build_slug)}/artifacts", {"limit": PAGE_LIMIT}
                    ):
                        rows = [
                            {
                                **artifact,
                                "app_slug": app_slug,
                                "build_slug": build_slug,
                                "build_triggered_at": build.get("triggered_at"),
                            }
                            for artifact in items
                        ]
                        if rows:
                            yield rows
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Bitrise: app {app_slug} not found while fetching artifacts, skipping")
            else:
                raise

        if index + 1 < len(remaining):
            resumable_source_manager.save_state(BitriseResumeConfig(app_slug=remaining[index + 1], next=None))


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BitriseResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    # One session reused across every page (and every app in a fan-out) so urllib3 keeps the
    # connection alive instead of re-handshaking per request.
    session = _get_session(api_token)
    fetch = _make_fetcher(session, logger)

    after = _build_after_param(should_use_incremental_field, db_incremental_field_last_value)

    if endpoint == "apps":
        yield from _get_apps_rows(fetch, resumable_source_manager)
    elif endpoint == "builds":
        yield from _get_builds_rows(fetch, resumable_source_manager, logger, after)
    elif endpoint == "workflows":
        yield from _get_workflows_rows(fetch, resumable_source_manager, logger)
    elif endpoint == "artifacts":
        yield from _get_artifacts_rows(fetch, resumable_source_manager, logger, after)
    else:
        raise ValueError(f"Unknown Bitrise endpoint: {endpoint}")


def bitrise_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BitriseResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = BITRISE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Bitrise returns builds newest-first and the fan-out walks app by app, so rows never
        # arrive in ascending timestamp order. desc mode persists the incremental watermark only
        # at successful job end, which is the only safe point for a fan-out stream.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
