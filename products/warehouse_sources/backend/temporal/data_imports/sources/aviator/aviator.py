import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.aviator.settings import (
    AVIATOR_ENDPOINTS,
    AviatorEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

AVIATOR_BASE_URL = "https://api.aviator.co/api/v1"

# GET /repo is capped at 10 results per page (documented).
REPO_PAGE_SIZE = 10
# Bound the config-history paginator so a misbehaving API can't loop forever.
CONFIG_HISTORY_MAX_PAGES = 1000
# Re-pull a trailing window of daily analytics each incremental run: recent days' aggregates can
# still be revised upstream. Merge dedupes the re-pulled days on the [repo, date] primary key.
ANALYTICS_LOOKBACK_DAYS = 7
# Series returned by GET /analytics. Each is a list of per-day objects carrying a `date` plus that
# series' metric fields; we merge them into one row per date, prefixing each metric with its series
# name (e.g. `time_in_queue_p50`) so the shared min/avg/pXX names don't collide.
_ANALYTICS_SERIES = (
    "time_in_queue",
    "wait_times_to_queue",
    "mergequeue_usage",
    "blocked_reason",
    "sync_frequency",
)


class AviatorRetryableError(Exception):
    pass


@dataclasses.dataclass
class AviatorResumeConfig:
    # Stable "org/name" keys of the fan-out repositories already fully processed in an earlier
    # attempt of this job. We resume by processing any repo NOT in this set, so a repo added between
    # a crash and the retry is picked up (a positional bookmark would silently skip it, and — because
    # fan-out persists the watermark only at successful job end — that skipped repo's older analytics
    # would then never be fetched outside the trailing lookback window). Empty for the non-fan-out
    # `repositories` endpoint, which is a short full-refresh list re-paginated from the start each run.
    completed_repo_keys: list[str] = dataclasses.field(default_factory=list)


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


@retry(
    retry=retry_if_exception_type(
        (
            AviatorRetryableError,
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
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    params: Optional[dict[str, Any]] = None,
) -> Any:
    response = session.get(url, headers=headers, params=params, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise AviatorRetryableError(f"Aviator API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Log only status and URL — never the response body. Aviator error bodies can echo
        # request-specific data (config-history diffs, token-like values), which must not spill
        # into application logs where access is broader than the source data itself.
        logger.error(f"Aviator API error: status={response.status_code}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_token: str) -> bool:
    """Probe the token with the cheapest account-level call. GET /repo needs no extra scope, so a
    200 confirms the token is genuine; a 401 means it is invalid or revoked."""
    try:
        response = make_tracked_session(redact_values=(api_token,)).get(
            f"{AVIATOR_BASE_URL}/repo", headers=_get_headers(api_token), params={"page": 1}, timeout=10
        )
        return response.status_code == 200
    except Exception:
        return False


def _iter_repositories(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[dict[str, Any]]:
    """Page through GET /repo yielding each {active, name, org, paused} object."""
    page = 1
    while True:
        data = _fetch(session, f"{AVIATOR_BASE_URL}/repo", headers, logger, params={"page": page})
        items = data if isinstance(data, list) else []
        yield from items
        # The list is short (10/page) and the last page is a partial (or empty) page.
        if len(items) < REPO_PAGE_SIZE:
            break
        page += 1


def _parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def _analytics_window(
    config: AviatorEndpointConfig, should_use_incremental_field: bool, db_incremental_field_last_value: Any
) -> tuple[str, str]:
    """Compute the (start, end) YYYY-MM-DD window for a GET /analytics request."""
    today = datetime.now(UTC).date()
    if should_use_incremental_field and db_incremental_field_last_value:
        # Advance from the stored watermark, minus a trailing safety window (recent aggregates get revised).
        start = _parse_date(db_incremental_field_last_value) - timedelta(days=ANALYTICS_LOOKBACK_DAYS)
    else:
        start = today - timedelta(days=config.default_lookback_days or 365)
    # A future-dated watermark (unexpected, but cheap to guard) would make start > end; clamp it.
    if start > today:
        start = today
    return start.isoformat(), today.isoformat()


def _flatten_analytics(repo: str, org: str, name: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge the five daily analytics series into one row per date for a single repository."""
    rows_by_date: dict[str, dict[str, Any]] = {}
    for series_name in _ANALYTICS_SERIES:
        series = payload.get(series_name)
        if not isinstance(series, list):
            continue
        for item in series:
            if not isinstance(item, dict):
                continue
            day = item.get("date")
            if not day:
                continue
            row = rows_by_date.setdefault(day, {"repo": repo, "org": org, "name": name, "date": day})
            for key, value in item.items():
                if key == "date":
                    continue
                row[f"{series_name}_{key}"] = value
    return [rows_by_date[day] for day in sorted(rows_by_date)]


def _extract_fan_out_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    endpoint: str,
    config: AviatorEndpointConfig,
    org: str,
    name: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[dict[str, Any]]:
    """Fetch one repository's rows for a fan-out endpoint, normalized to flat dicts."""
    url = f"{AVIATOR_BASE_URL}{config.path}"

    if endpoint == "merge_queue_analytics":
        start, end = _analytics_window(config, should_use_incremental_field, db_incremental_field_last_value)
        payload = _fetch(session, url, headers, logger, params={"repo": f"{org}/{name}", "start": start, "end": end})
        yield from _flatten_analytics(f"{org}/{name}", org, name, payload)
        return

    if endpoint == "queued_pull_requests":
        payload = _fetch(session, url, headers, logger, params={"org": org, "repo": name})
        for pr in payload.get("pull_requests", []):
            # `number` is part of the (org, repo, number) primary key. A row missing it would merge
            # under a null key, silently collapsing every such PR in the repo into one row — skip it.
            if pr.get("number") is None:
                logger.warning(f"Aviator: skipping queued pull request without a number for {org}/{name}")
                continue
            pr.pop("repository", None)  # Redundant with the injected org/repo below.
            yield {**pr, "org": org, "repo": name}
        return

    if endpoint == "queue_stats":
        payload = _fetch(session, url, headers, logger, params={"org": org, "repo": name})
        depth = payload.get("depth", {})
        yield {
            "org": org,
            "repo": name,
            "queued": depth.get("queued"),
            "processing": depth.get("processing"),
            "waiting": depth.get("waiting"),
        }
        return

    if endpoint == "config_history":
        page = 1
        while page <= CONFIG_HISTORY_MAX_PAGES:
            payload = _fetch(session, url, headers, logger, params={"org": org, "repo": name, "page": page})
            history = payload.get("history", [])
            if not history:
                break
            for change in history:
                # `applied_at` is part of the (org, repo, applied_at) primary key. A row missing it
                # would merge under a null key, collapsing multiple config changes into one — skip it.
                applied_at = change.get("applied_at")
                if not applied_at:
                    logger.warning(f"Aviator: skipping config history entry without applied_at for {org}/{name}")
                    continue
                applied_by = change.get("applied_by") or {}
                yield {
                    "org": org,
                    "repo": name,
                    "applied_at": applied_at,
                    "commit_sha": change.get("commit_sha"),
                    "diff": change.get("diff"),
                    "applied_by_email": applied_by.get("email"),
                    "applied_by_gh_username": applied_by.get("gh_username"),
                }
            page += 1
        else:
            logger.warning(f"Aviator config_history hit the page cap ({CONFIG_HISTORY_MAX_PAGES}) for {org}/{name}")
        return

    raise ValueError(f"Unknown fan-out endpoint: {endpoint}")


def _get_repository_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
) -> Iterator[Any]:
    for repo in _iter_repositories(session, headers, logger):
        batcher.batch(repo)
        if batcher.should_yield():
            yield batcher.get_table()


def _get_fan_out_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[AviatorResumeConfig],
    endpoint: str,
    config: AviatorEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[Any]:
    repos = list(_iter_repositories(session, headers, logger))

    # Resume by skipping only repos already fully processed in an earlier attempt of this job. Keyed
    # on stable "org/name" (not a positional index) so a repo added between a crash and the retry is
    # still processed rather than skipped — skipping it would strand its older rows, since fan-out
    # persists the watermark only at successful job end. Within a repo we always re-fetch from the
    # start, so this is at repo granularity only; merge dedupes any re-pulled rows on the primary key.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    completed_repo_keys = list(resume.completed_repo_keys) if resume is not None else []
    completed = set(completed_repo_keys)

    for repo in repos:
        org, name = repo.get("org"), repo.get("name")
        if not org or not name:
            continue
        repo_key = f"{org}/{name}"
        if repo_key in completed:
            logger.debug(f"Aviator: skipping already-processed repo={repo_key} for {endpoint} fan-out")
            continue

        for row in _extract_fan_out_rows(
            session,
            headers,
            logger,
            endpoint,
            config,
            org,
            name,
            should_use_incremental_field,
            db_incremental_field_last_value,
        ):
            batcher.batch(row)
            if batcher.should_yield():
                yield batcher.get_table()

        # Mark this repo done so a crash resumes with the repos still owed. Saved AFTER yielding this
        # repo's batches so a crash mid-repo re-processes it (merge dedupes) rather than skipping it.
        completed_repo_keys.append(repo_key)
        completed.add(repo_key)
        resumable_source_manager.save_state(AviatorResumeConfig(completed_repo_keys=list(completed_repo_keys)))


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AviatorResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = AVIATOR_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)
    # One session reused across every page and every fan-out repo so urllib3 keeps the connection alive.
    # Register the token for value-based redaction so it can't surface in logged URLs or captured samples.
    session = make_tracked_session(redact_values=(api_token,))
    batcher = Batcher(logger=logger)

    if config.fan_out_over_repos:
        yield from _get_fan_out_rows(
            session,
            headers,
            logger,
            batcher,
            resumable_source_manager,
            endpoint,
            config,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    else:
        yield from _get_repository_rows(session, headers, logger, batcher)

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def aviator_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AviatorResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = AVIATOR_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        # Fan-out runs persist the incremental watermark only at successful job end (desc mode): a
        # partial run's max date says nothing about repos it never reached, so per-batch persistence
        # could advance the watermark past rows a crashed run still owes.
        sort_mode="desc" if config.fan_out_over_repos else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
