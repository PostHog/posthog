from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import requests
from requests.auth import HTTPBasicAuth
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.sources.appbot.settings import APPBOT_ENDPOINTS
from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    format_datetime,
    frozen,
    make_tracked_session,
    raise_for_retryable_status,
    raise_for_status_redacted,
    reach_safe_point,
    resolve_incremental_start,
    validate_via_probe,
    vendor_retry,
)

APPBOT_BASE_URL = "https://api.appbot.co/api/v2"
REQUEST_TIMEOUT_SECONDS = 60

# The earliest date a full refresh reads from. Appbot defaults `start` to 90 days ago when it is left
# out, so a full refresh must send it. The app stores opened in 2008.
HISTORY_START = datetime(2008, 1, 1, tzinfo=UTC)

# Appbot serves at most 50,000 reviews for one query through `page`. A date window that holds more
# is split in two until each part fits.
MAX_REVIEWS_PER_WINDOW = 50_000
# A safety valve for a server that ignores `page`. 50,000 reviews at 20 per page is 2,500 pages.
MAX_REVIEW_PAGES_PER_WINDOW = 3_000

# Reviews can reach Appbot some days after the store publish date, and a reply or a sentiment can
# change later, so an incremental run reads the last week again. Merge dedupes the overlap.
REVIEWS_LOOKBACK = timedelta(days=7)
# Ratings snapshots of different apps are not collected at the same moment.
RATINGS_LOOKBACK = timedelta(days=2)

RATINGS_PAGE_SIZE = 1000

# The statuses Appbot can send for a bulk ratings page token that is no longer valid. The docs do not
# name one, so a 404 counts too: the next attempt lists the apps again and skips a removed app.
EXPIRED_TOKEN_STATUSES = (400, 404, 410, 422)


@frozen
class AppbotResumeConfig:
    # Apps whose rows are all yielded. A set of ids, not a list position, so a resume against an app
    # list in another order, or with new apps, skips no app.
    done_app_ids: list[int] | None = None
    # The app that was read when the state was saved.
    app_id: int | None = None
    # Reviews: the date windows ([start, end] as yyyy-mm-dd) still to read for `app_id`, oldest first,
    # and the page of the first window to read next.
    windows: list[list[str]] | None = None
    page: int = 1
    # Ratings: the token of the next bulk page. Appbot expires it after 10 minutes.
    next_page_token: str | None = None


@frozen
class ReviewWindow:
    start: date
    end: date


class AppbotIncompleteReadError(Exception):
    pass


class AppbotPageTokenExpiredError(Exception):
    pass


def make_session(username: str, password: str) -> requests.Session:
    session = make_tracked_session(redact_values=(password,), allow_redirects=False)
    session.auth = HTTPBasicAuth(username, password)
    return session


def validate_credentials(username: str, password: str) -> tuple[bool, str | None]:
    # /me does not count against the monthly request quota.
    _ok, status = validate_via_probe(
        lambda: make_session(username, password), f"{APPBOT_BASE_URL}/me", allow_redirects=False
    )
    if status == 200:
        return True, None
    if status in (401, 403):
        return (
            False,
            "Appbot didn't accept this API username and password. Check them on the API page in Appbot. The Appbot API needs a plan with the API add-on.",
        )
    if status is None:
        return False, "Couldn't reach the Appbot API. Try again in a few minutes."
    return False, f"The Appbot API returned an unexpected status code ({status}). Try again in a few minutes."


@vendor_retry(attempts=6, backoff_max=60.0, safe_point=reach_safe_point)
def _fetch(session: requests.Session, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{APPBOT_BASE_URL}{path}"
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    # Appbot allows a burst of 20 requests a minute.
    raise_for_retryable_status(response, vendor="Appbot", url=url)
    raise_for_status_redacted(response, url=url)
    return response.json()


def _list_apps(session: requests.Session) -> list[dict[str, Any]]:
    return _fetch(session, "/apps").get("results") or []


def _status_of(exc: requests.HTTPError) -> int | None:
    return exc.response.status_code if exc.response is not None else None


def _load_resume(manager: ResumableSourceManager[AppbotResumeConfig]) -> AppbotResumeConfig | None:
    return manager.load_state() if manager.can_resume() else None


def _worklist(app_ids: list[int], resume: AppbotResumeConfig | None) -> list[int]:
    """The apps still to read, with the app of a resumed run first."""
    if resume is None:
        return app_ids
    done = set(resume.done_app_ids or [])
    remaining = [app_id for app_id in app_ids if app_id not in done]
    if resume.app_id in remaining:
        remaining.remove(resume.app_id)
        remaining.insert(0, resume.app_id)
    return remaining


def _split_window(window: ReviewWindow) -> list[ReviewWindow]:
    middle = window.start + timedelta(days=(window.end - window.start).days // 2)
    return [
        ReviewWindow(start=window.start, end=middle),
        ReviewWindow(start=middle + timedelta(days=1), end=window.end),
    ]


def _encode_windows(windows: list[ReviewWindow]) -> list[list[str]]:
    return [[window.start.isoformat(), window.end.isoformat()] for window in windows]


def _decode_windows(windows: list[list[str]]) -> list[ReviewWindow]:
    return [ReviewWindow(start=date.fromisoformat(start), end=date.fromisoformat(end)) for start, end in windows]


def _app_review_rows(
    session: requests.Session,
    app_id: int,
    windows: list[ReviewWindow],
    page: int,
    done_app_ids: list[int],
    manager: ResumableSourceManager[AppbotResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    pages_in_window = 0
    while windows:
        window = windows[0]
        data = _fetch(
            session,
            f"/apps/{app_id}/reviews",
            {"start": window.start.isoformat(), "end": window.end.isoformat(), "page": page},
        )

        total_count = data.get("total_count")
        if page == 1 and isinstance(total_count, int) and total_count > MAX_REVIEWS_PER_WINDOW:
            if window.start >= window.end:
                raise AppbotIncompleteReadError(
                    f"Appbot has {total_count} reviews for app {app_id} on {window.start}, more than the "
                    f"{MAX_REVIEWS_PER_WINDOW} reviews its API can page through for one day"
                )
            windows = [*_split_window(window), *windows[1:]]
            manager.save_state(
                AppbotResumeConfig(done_app_ids=done_app_ids, app_id=app_id, windows=_encode_windows(windows), page=1)
            )
            manager.safe_point()
            continue

        rows = data.get("results") or []
        pages_in_window += 1
        total_pages = data.get("total_pages")
        has_next_page = bool(rows) and (page < total_pages if isinstance(total_pages, int) else True)
        if has_next_page and pages_in_window >= MAX_REVIEW_PAGES_PER_WINDOW:
            # Advancing past the window would let the watermark move over reviews that were never read.
            raise AppbotIncompleteReadError(
                f"Appbot returned more than {MAX_REVIEW_PAGES_PER_WINDOW} pages of reviews for app {app_id} "
                f"from {window.start} to {window.end}"
            )

        if has_next_page:
            page += 1
        else:
            windows = windows[1:]
            page = 1
            pages_in_window = 0

        if windows:
            manager.save_state(
                AppbotResumeConfig(
                    done_app_ids=done_app_ids, app_id=app_id, windows=_encode_windows(windows), page=page
                )
            )
        else:
            manager.save_state(AppbotResumeConfig(done_app_ids=[*done_app_ids, app_id]))

        if rows:
            # The documented example shows a placeholder in `app_id`, so the key column comes from
            # the app this request was for.
            yield [{**row, "app_id": app_id} for row in rows]
        else:
            manager.safe_point()


def _reviews_rows(
    session: requests.Session,
    start: date,
    end: date,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AppbotResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    app_ids = [app["id"] for app in _list_apps(session)]
    resume = _load_resume(manager)
    done_app_ids = list(resume.done_app_ids or []) if resume else []

    for index, app_id in enumerate(_worklist(app_ids, resume)):
        if index == 0 and resume is not None and resume.app_id == app_id and resume.windows:
            windows = _decode_windows(resume.windows)
            page = resume.page
        else:
            windows = [ReviewWindow(start=start, end=end)]
            page = 1

        try:
            yield from _app_review_rows(session, app_id, windows, page, done_app_ids, manager)
        except requests.HTTPError as exc:
            # An app removed from the team after the app list was read.
            if _status_of(exc) != 404:
                raise
            logger.warning(f"Appbot: app {app_id} not found while reading reviews, skipping it")
            manager.save_state(AppbotResumeConfig(done_app_ids=[*done_app_ids, app_id]))
            manager.safe_point()
        done_app_ids = [*done_app_ids, app_id]


def _ratings_row(app_id: int, row: dict[str, Any]) -> dict[str, Any]:
    country_id = row.get("country_id")
    country_key = "all" if country_id is None else str(country_id)
    return {**row, "app_id": app_id, "id": f"{app_id}:{country_key}:{row.get('created_at')}"}


def _app_ratings_rows(
    session: requests.Session,
    app_id: int,
    start: str,
    token: str | None,
    done_app_ids: list[int],
    manager: ResumableSourceManager[AppbotResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    # Every page after the first must repeat the query of the first page.
    params: dict[str, Any] = {"start": start, "page_size": RATINGS_PAGE_SIZE}
    while True:
        try:
            data = _fetch(
                session,
                f"/apps/{app_id}/ratings/bulk",
                {**params, "next_page_token": token} if token else params,
            )
        except requests.HTTPError as exc:
            if token is not None and _status_of(exc) in EXPIRED_TOKEN_STATUSES:
                raise AppbotPageTokenExpiredError(
                    f"Appbot refused the ratings page token for app {app_id} (status {_status_of(exc)})"
                ) from exc
            raise

        rows = data.get("results") or []
        token = data.get("next_page_token") or None

        if token:
            manager.save_state(AppbotResumeConfig(done_app_ids=done_app_ids, app_id=app_id, next_page_token=token))
        else:
            manager.save_state(AppbotResumeConfig(done_app_ids=[*done_app_ids, app_id]))

        if rows:
            yield [_ratings_row(app_id, row) for row in rows]
        else:
            manager.safe_point()

        if not token:
            return


def _ratings_rows(
    session: requests.Session,
    start: str,
    logger: FilteringBoundLogger,
    manager: ResumableSourceManager[AppbotResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    app_ids = [app["id"] for app in _list_apps(session)]
    resume = _load_resume(manager)
    done_app_ids = list(resume.done_app_ids or []) if resume else []

    for index, app_id in enumerate(_worklist(app_ids, resume)):
        token = resume.next_page_token if index == 0 and resume is not None and resume.app_id == app_id else None

        try:
            yield from _app_ratings_rows(session, app_id, start, token, done_app_ids, manager)
        except AppbotPageTokenExpiredError:
            # Pages of this app before the token can already be in the table, and a first sync or a
            # full refresh appends, so reading the app again here would store those rows twice. Drop
            # the cursor instead: the retried attempt reads the whole table again and replaces it.
            logger.warning(f"Appbot: ratings page token for app {app_id} expired, restarting the sync")
            manager.clear_state()
            raise
        except requests.HTTPError as exc:
            # An app removed from the team after the app list was read.
            if _status_of(exc) != 404:
                raise
            logger.warning(f"Appbot: app {app_id} not found while reading ratings, skipping it")
            manager.save_state(AppbotResumeConfig(done_app_ids=[*done_app_ids, app_id]))
            manager.safe_point()
        done_app_ids = [*done_app_ids, app_id]


def _today() -> date:
    return datetime.now(UTC).date()


def appbot_source(
    username: str,
    password: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AppbotResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = APPBOT_ENDPOINTS[endpoint]

    def items() -> Iterator[list[dict[str, Any]]]:
        session = make_session(username, password)
        if config.kind == "apps":
            yield _list_apps(session)
        elif config.kind == "reviews":
            start = resolve_incremental_start(
                should_use_incremental_field,
                db_incremental_field_last_value,
                default=HISTORY_START,
                lookback=REVIEWS_LOOKBACK,
            )
            yield from _reviews_rows(session, start.date(), _today(), logger, resumable_source_manager)
        else:
            start = resolve_incremental_start(
                should_use_incremental_field,
                db_incremental_field_last_value,
                default=HISTORY_START,
                lookback=RATINGS_LOOKBACK,
            )
            yield from _ratings_rows(session, format_datetime(start, "iso_z"), logger, resumable_source_manager)

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
