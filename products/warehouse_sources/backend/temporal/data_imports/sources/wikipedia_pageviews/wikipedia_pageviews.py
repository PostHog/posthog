import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.wikipedia_pageviews.settings import (
    ARTICLE_PAGEVIEWS_ENDPOINT,
    BASE_URL,
    DATA_START_DATE,
    MAX_ARTICLES,
    TOP_ARTICLES_ENDPOINT,
    TOP_WINDOW_DAYS,
    USER_AGENT,
    WIKIPEDIA_PAGEVIEWS_ENDPOINTS,
    WINDOW_DAYS,
)

REQUEST_TIMEOUT_SECONDS = 60

NO_ARTICLES_ERROR = "No article titles configured for the article_pageviews table"


@dataclasses.dataclass
class WikipediaPageviewsResumeConfig:
    # ISO date (YYYY-MM-DD) of the first day the next window should fetch.
    next_start: str


def _normalize_project(project: str) -> str:
    project = project.strip().lower()
    project = re.sub(r"^https?://", "", project)
    return project.strip("/")


def _parse_articles(article_names: Optional[str]) -> list[str]:
    if not article_names:
        return []
    articles: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"[,\n]", article_names):
        # The API identifies articles in URL form, with underscores instead of spaces.
        article = raw.strip().replace(" ", "_")
        # Dedupe so a repeated title doesn't refetch the same per-article window.
        if article and article not in seen:
            seen.add(article)
            articles.append(article)
    return articles


def _coerce_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        # API day identifiers: YYYYMMDD or YYYYMMDDHH.
        if re.fullmatch(r"\d{8}(\d{2})?", stripped):
            try:
                return datetime.strptime(stripped[:8], "%Y%m%d").date()
            except ValueError:
                return None
        try:
            return datetime.fromisoformat(stripped).date()
        except ValueError:
            return None
    return None


def _timestamp_to_datetime(timestamp: str) -> datetime:
    return datetime.strptime(timestamp, "%Y%m%d%H").replace(tzinfo=UTC)


def _with_date(item: dict[str, Any]) -> dict[str, Any]:
    """Attach a parsed `date` column, the typed cursor/partition field for the row's day."""
    timestamp = item.get("timestamp")
    if isinstance(timestamp, str):
        try:
            item["date"] = _timestamp_to_datetime(timestamp)
        except ValueError:
            pass
    return item


def _get_items(session: requests.Session, url: str, logger: FilteringBoundLogger) -> list[dict[str, Any]]:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    # The API 404s windows with no data — normal for days newer than the ~1-day ingestion lag
    # or older than the project's history. An unknown project 404s identically, but project
    # validity is checked at source creation, so here a 404 is just an empty window.
    if response.status_code == 404:
        logger.debug(f"Wikipedia Pageviews: no data for {url}")
        return []

    if not response.ok:
        logger.error(
            f"Wikipedia Pageviews API error: status={response.status_code}, body={response.text[:500]}, url={url}"
        )
        response.raise_for_status()

    items = response.json().get("items", [])
    return items if isinstance(items, list) else []


def _aggregate_rows(
    session: requests.Session,
    project: str,
    access: str,
    agent: str,
    window_start: date,
    window_end: date,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    url = (
        f"{BASE_URL}/pageviews/aggregate/{quote(project, safe='')}/{access}/{agent}"
        f"/daily/{window_start:%Y%m%d}00/{window_end:%Y%m%d}00"
    )
    return [_with_date(item) for item in _get_items(session, url, logger)]


def _article_rows(
    session: requests.Session,
    project: str,
    access: str,
    agent: str,
    articles: list[str],
    window_start: date,
    window_end: date,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for article in articles:
        url = (
            f"{BASE_URL}/pageviews/per-article/{quote(project, safe='')}/{access}/{agent}"
            f"/{quote(article, safe='')}/daily/{window_start:%Y%m%d}/{window_end:%Y%m%d}"
        )
        rows.extend(_with_date(item) for item in _get_items(session, url, logger))
    return rows


def _top_rows(
    session: requests.Session,
    project: str,
    access: str,
    day: date,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    url = f"{BASE_URL}/pageviews/top/{quote(project, safe='')}/{access}/{day:%Y}/{day:%m}/{day:%d}"
    rows: list[dict[str, Any]] = []
    for item in _get_items(session, url, logger):
        for article in item.get("articles") or []:
            rows.append(
                {
                    "project": item.get("project"),
                    "access": item.get("access"),
                    "year": item.get("year"),
                    "month": item.get("month"),
                    "day": item.get("day"),
                    "date": datetime(day.year, day.month, day.day, tzinfo=UTC),
                    "article": article.get("article"),
                    "views": article.get("views"),
                    "rank": article.get("rank"),
                }
            )
    return rows


def _get_rows(
    project: str,
    access: str,
    agent: str,
    article_names: Optional[str],
    start_date: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[WikipediaPageviewsResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    normalized_project = _normalize_project(project)
    session = make_tracked_session(headers={"User-Agent": USER_AGENT})

    articles: list[str] = []
    if endpoint == ARTICLE_PAGEVIEWS_ENDPOINT:
        articles = _parse_articles(article_names)
        if not articles:
            raise ValueError(NO_ARTICLES_ERROR)
        # Runtime cap as well as setup validation, so a config stored before the limit
        # existed (or one that bypassed validation) can't fan out past MAX_ARTICLES.
        if len(articles) > MAX_ARTICLES:
            logger.warning(
                f"Wikipedia Pageviews: {len(articles)} article titles configured, syncing only the first {MAX_ARTICLES}"
            )
            articles = articles[:MAX_ARTICLES]

    # The API truncates ranges at the newest loaded day and 404s fully-empty windows (treated
    # as empty above), so today is a safe end boundary despite the ~1-day ingestion lag.
    end_boundary = datetime.now(UTC).date()

    # Clamp to the first day data exists: a stored start_date like 0001-01-01 parses fine but
    # would otherwise fan out into hundreds of thousands of empty daily requests (the top
    # endpoint serves one day per request).
    start = max(_coerce_date(start_date) or DATA_START_DATE, DATA_START_DATE)
    if should_use_incremental_field:
        last_value = _coerce_date(db_incremental_field_last_value)
        if last_value is not None:
            # Restart at the watermark day itself, not the day after: the newest loaded days
            # can be revised while ingestion settles, and merge dedupes on the primary key.
            start = max(start, last_value)

    # A persisted resume cursor takes precedence so a heartbeat-timed-out activity picks up at
    # the window it was processing rather than recomputing from the incremental value.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        resumed = _coerce_date(resume.next_start)
        if resumed is not None:
            start = resumed
            logger.debug(f"Wikipedia Pageviews: resuming {endpoint} from {start.isoformat()}")

    window_days = TOP_WINDOW_DAYS if endpoint == TOP_ARTICLES_ENDPOINT else WINDOW_DAYS

    cursor = start
    while cursor <= end_boundary:
        window_end = min(cursor + timedelta(days=window_days - 1), end_boundary)

        if endpoint == TOP_ARTICLES_ENDPOINT:
            rows = []
            day = cursor
            while day <= window_end:
                rows.extend(_top_rows(session, normalized_project, access, day, logger))
                day += timedelta(days=1)
        elif endpoint == ARTICLE_PAGEVIEWS_ENDPOINT:
            rows = _article_rows(session, normalized_project, access, agent, articles, cursor, window_end, logger)
        else:
            rows = _aggregate_rows(session, normalized_project, access, agent, cursor, window_end, logger)

        if rows:
            yield rows

        cursor = window_end + timedelta(days=1)
        # Save AFTER yielding so a crash re-fetches (and merge dedupes) the last window
        # instead of skipping it.
        resumable_source_manager.save_state(WikipediaPageviewsResumeConfig(next_start=cursor.isoformat()))


def wikipedia_pageviews_source(
    project: str,
    access: str,
    agent: str,
    article_names: Optional[str],
    start_date: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[WikipediaPageviewsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = WIKIPEDIA_PAGEVIEWS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: _get_rows(
            project=project,
            access=access,
            agent=agent,
            article_names=article_names,
            start_date=start_date,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
        sort_mode="asc",
    )


def validate_project(project: str, access: str, agent: str) -> tuple[bool, Optional[str]]:
    normalized_project = _normalize_project(project)
    if not normalized_project:
        return False, "Enter a Wikimedia project domain (e.g. en.wikipedia.org)."

    session = make_tracked_session(headers={"User-Agent": USER_AGENT})
    # Probe a window that ends before the ~1-2 day ingestion lag, so a valid project can't 404
    # just because the newest days aren't loaded yet.
    probe_end = datetime.now(UTC).date() - timedelta(days=3)
    probe_start = probe_end - timedelta(days=7)
    url = (
        f"{BASE_URL}/pageviews/aggregate/{quote(normalized_project, safe='')}/{access}/{agent}"
        f"/daily/{probe_start:%Y%m%d}00/{probe_end:%Y%m%d}00"
    )
    try:
        response = session.get(url, timeout=30)
    except Exception as e:
        return False, f"Could not reach the Wikimedia API ({e}). Please retry."

    if response.status_code == 200:
        return True, None
    if response.status_code == 404:
        return (
            False,
            f"No pageview data found for project '{normalized_project}'. "
            "Check the project domain (e.g. en.wikipedia.org).",
        )
    return False, f"Unexpected response from the Wikimedia API (status {response.status_code})."
