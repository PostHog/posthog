import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.settings import (
    APPFOLLOW_ENDPOINTS,
    DEFAULT_START_DATE,
    AppfollowEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

APPFOLLOW_BASE_URL = "https://api.appfollow.io/api/v2"

# Ratings history is offset/limit paginated; reviews use page/pages_count. Both cap a page at 100 rows.
DEFAULT_PAGE_SIZE = 100


class AppfollowRetryableError(Exception):
    pass


@dataclasses.dataclass
class AppfollowResumeConfig:
    # Fan-out bookmark: the store `ext_id` currently being processed. A stable id (not a positional
    # index) so apps added/removed between a crash and the retry can't resume us into the wrong app.
    # `None` for the top-level (`app_collections`, `users`, `app_lists`) endpoints.
    ext_id: str | None = None
    # Pagination cursor within the current app's resource: 1-indexed `page` for reviews, or the row
    # `offset` for ratings history.
    cursor: int | None = None


def _headers(api_key: str) -> dict[str, str]:
    return {"X-AppFollow-API-Token": api_key, "Accept": "application/json"}


def _today_str() -> str:
    return datetime.now(UTC).date().isoformat()


def _to_date_str(value: Any) -> str | None:
    """Format a datetime/date/ISO-string value as the yyyy-mm-dd AppFollow date filters expect."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).date().isoformat() if value.tzinfo else value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)[:10]
    try:
        date.fromisoformat(text)
    except ValueError:
        return None
    return text


def _to_datetime_str(value: Any) -> str | None:
    """Format the reviews `last_modified` filter value.

    AppFollow documents `last_modified` as a date-time; the exact accepted format isn't published and
    we have no credentials to probe it, so we send `YYYY-MM-DD HH:MM:SS` (UTC). A `date` is widened to
    the start of that day.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return f"{value.isoformat()} 00:00:00"
    return str(value)


def _clamp_future_value_to_now(value: Any) -> Any:
    """Cap a future datetime/date incremental cursor at now.

    A future-dated record would push the cursor past now, and every later sync would then filter on a
    future timestamp — a no-op that can silently freeze the table. Clamping keeps the filter meaningful
    and lets the sync self-heal.
    """
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    return value


@retry(
    retry=retry_if_exception_type(
        (
            AppfollowRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> Any:
    response = session.get(url, params=params, timeout=60)

    # AppFollow rate-limits per token (1000/hr) and per account (10000/hr); treat 429 and transient
    # 5xx as retryable. 401 (bad token) / 402 (out of credits) / 403 raise for the caller and are
    # mapped to non-retryable errors at the source layer.
    if response.status_code == 429 or response.status_code >= 500:
        raise AppfollowRetryableError(f"AppFollow API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"AppFollow API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _extract_rows(data: Any, data_key: str | None) -> list[dict[str, Any]]:
    """Pull the row list out of an AppFollow response.

    Rows live either at the response root (``data_key is None``) or under a single body key
    (e.g. ``apps``, ``reviews``, ``ratings``). Anything unexpected degrades to an empty page rather
    than raising, since AppFollow occasionally returns a non-list error envelope with HTTP 200.
    """
    if data_key is None:
        return data if isinstance(data, list) else []
    value = data.get(data_key) if isinstance(data, dict) else None
    return value if isinstance(value, list) else []


def check_credentials(api_key: str) -> int | None:
    """Probe the account collections endpoint and return its HTTP status, or None on a network error.

    ``/account/apps`` costs a single credit and is reachable by any valid token, so it's the cheapest
    genuine liveness check. 200 = valid, 401 = bad token, 402 = out of credits.
    """
    try:
        response = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,)).get(
            f"{APPFOLLOW_BASE_URL}/account/apps", timeout=10
        )
        return response.status_code
    except Exception:
        return None


def _iter_collections(session: requests.Session, logger: FilteringBoundLogger) -> Iterator[dict[str, Any]]:
    data = _fetch(session, f"{APPFOLLOW_BASE_URL}/account/apps", {}, logger)
    yield from _extract_rows(data, "apps")


def _iter_apps(session: requests.Session, logger: FilteringBoundLogger) -> Iterator[dict[str, Any]]:
    """Fan out over every collection and yield each app row, enriched for keying and downstream fan-out.

    Each app row is stamped with its `app_collection_id` and `collection_name`, and `ext_id`/`store`
    are lifted from the nested `app` object to the top level when absent so the review/rating fan-outs
    and the composite primary key can rely on them.
    """
    for collection in _iter_collections(session, logger):
        collection_id = collection.get("id")
        collection_name = collection.get("title_normalized") or collection.get("title")
        data = _fetch(session, f"{APPFOLLOW_BASE_URL}/account/apps/app", {"apps_id": collection_id}, logger)
        for app in _extract_rows(data, "apps_app"):
            nested = app.get("app") or {}
            app["app_collection_id"] = collection_id
            app["collection_name"] = collection_name
            if not app.get("ext_id") and (nested_ext_id := nested.get("ext_id")):
                app["ext_id"] = nested_ext_id
            if not app.get("store") and (nested_store := nested.get("store")):
                app["store"] = nested_store
            yield app


@dataclasses.dataclass
class _AppTarget:
    ext_id: str
    store: str | None
    collection_name: str | None


def _iter_app_targets(
    session: requests.Session, logger: FilteringBoundLogger, *, dedupe_by_store: bool
) -> list[_AppTarget]:
    """Discover the apps the review/rating fan-outs iterate.

    Reviews key on `ext_id` alone; ratings key on `ext_id` + `store`. The same app can appear in
    several collections, so we de-duplicate to avoid fetching (and paying credits for) it twice.
    """
    seen: set[tuple[str, str | None]] = set()
    targets: list[_AppTarget] = []
    for app in _iter_apps(session, logger):
        ext_id = app.get("ext_id")
        if not ext_id:
            continue
        store = app.get("store")
        key = (str(ext_id), store if dedupe_by_store else None)
        if key in seen:
            continue
        seen.add(key)
        targets.append(_AppTarget(ext_id=str(ext_id), store=store, collection_name=app.get("collection_name")))
    return targets


def _resume_slice(
    targets: list[_AppTarget], manager: ResumableSourceManager[AppfollowResumeConfig]
) -> tuple[list[_AppTarget], int]:
    """Resolve the saved ext_id bookmark to the remaining targets and the cursor to resume the first at.

    If the bookmarked app no longer exists (removed between runs) we start over from the first app —
    merge dedupes the re-pulled rows on the primary key.
    """
    resume = manager.load_state() if manager.can_resume() else None
    if resume is None or resume.ext_id is None:
        return targets, 0
    index = next((i for i, t in enumerate(targets) if t.ext_id == resume.ext_id), None)
    if index is None:
        return targets, 0
    return targets[index:], resume.cursor or 0


def _get_list(
    session: requests.Session,
    config: AppfollowEndpointConfig,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    data = _fetch(session, f"{APPFOLLOW_BASE_URL}{config.path}", {}, logger)
    rows = _extract_rows(data, config.data_key)
    if rows:
        yield rows


def _get_apps(
    session: requests.Session,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    rows = list(_iter_apps(session, logger))
    if rows:
        yield rows


def _get_reviews(
    session: requests.Session,
    config: AppfollowEndpointConfig,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AppfollowResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    targets = _iter_app_targets(session, logger, dedupe_by_store=False)
    remaining, resume_page = _resume_slice(targets, manager)

    last_modified: str | None = None
    if should_use_incremental_field and db_incremental_field_last_value:
        last_modified = _to_datetime_str(_clamp_future_value_to_now(db_incremental_field_last_value))

    to_date = _today_str()
    for i, target in enumerate(remaining):
        page = resume_page if i == 0 and resume_page else 1
        while True:
            params: dict[str, Any] = {
                "ext_id": target.ext_id,
                "from": DEFAULT_START_DATE,
                "to": to_date,
                "page": page,
            }
            if last_modified:
                params["last_modified"] = last_modified

            data = _fetch(session, f"{APPFOLLOW_BASE_URL}{config.path}", params, logger)
            rows = _extract_rows(data, config.data_key)
            pages_count = int(data.get("pages_count") or data.get("pages") or 1) if isinstance(data, dict) else 1

            if rows:
                for row in rows:
                    row.setdefault("ext_id", target.ext_id)
                yield rows

            if not rows or page >= pages_count:
                break

            page += 1
            # Save AFTER yielding so a crash re-fetches the current page rather than skipping it; merge
            # dedupes the re-pulled rows on the [ext_id, review_id] primary key.
            manager.save_state(AppfollowResumeConfig(ext_id=target.ext_id, cursor=page))

        # Advance the bookmark to the next app so a crash between apps resumes correctly.
        if i + 1 < len(remaining):
            manager.save_state(AppfollowResumeConfig(ext_id=remaining[i + 1].ext_id, cursor=1))


def _get_ratings(
    session: requests.Session,
    config: AppfollowEndpointConfig,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AppfollowResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    targets = _iter_app_targets(session, logger, dedupe_by_store=True)
    remaining, resume_offset = _resume_slice(targets, manager)

    from_date = DEFAULT_START_DATE
    if should_use_incremental_field and db_incremental_field_last_value:
        from_date = _to_date_str(_clamp_future_value_to_now(db_incremental_field_last_value)) or DEFAULT_START_DATE

    to_date = _today_str()
    limit = config.page_size or DEFAULT_PAGE_SIZE
    for i, target in enumerate(remaining):
        # Ratings history requires a store; skip apps whose store we couldn't resolve rather than 422.
        if not target.store:
            continue
        offset = resume_offset if i == 0 and resume_offset else 0
        while True:
            params: dict[str, Any] = {
                "ext_id": target.ext_id,
                "store": target.store,
                "from": from_date,
                "to": to_date,
                "period": "daily",
                "type": "total",
                "offset": offset,
                "limit": limit,
            }
            if target.collection_name:
                params["collection_name"] = target.collection_name

            data = _fetch(session, f"{APPFOLLOW_BASE_URL}{config.path}", params, logger)
            rows = _extract_rows(data, config.data_key)

            if rows:
                for row in rows:
                    row.setdefault("ext_id", target.ext_id)
                    row.setdefault("store", target.store)
                yield rows

            if len(rows) < limit:
                break

            offset += limit
            manager.save_state(AppfollowResumeConfig(ext_id=target.ext_id, cursor=offset))

        if i + 1 < len(remaining):
            manager.save_state(AppfollowResumeConfig(ext_id=remaining[i + 1].ext_id, cursor=0))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AppfollowResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = APPFOLLOW_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    if config.kind == "list":
        yield from _get_list(session, config, logger)
    elif config.kind == "apps":
        yield from _get_apps(session, logger)
    elif config.kind == "reviews":
        yield from _get_reviews(
            session,
            config,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    else:  # "ratings"
        yield from _get_ratings(
            session,
            config,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )


def appfollow_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AppfollowResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = APPFOLLOW_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # We re-open the full incremental window each run (reviews filter on `last_modified`, ratings on
        # `from`) and rely on merge to dedupe, so every in-window row is written regardless of the order
        # AppFollow returns pages in — "asc" simply lets the watermark checkpoint after each batch.
        sort_mode="asc",
    )
