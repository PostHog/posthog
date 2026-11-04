import re
import datetime as dt
from collections.abc import Callable, Iterator
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.sources.rubygems.settings import RUBYGEMS_ENDPOINTS, RubyGemsEndpointConfig
from products.warehouse_sources.sources.sdk import (
    SourceResponse,
    make_tracked_session,
    parse_datetime_value,
    retry_with_deadline,
)

RUBYGEMS_BASE_URL = "https://rubygems.org/api/v1"

REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRY_ATTEMPTS = 5

# Each configured gem costs one request per enabled stream on every sync (full refresh, no bulk
# enumeration endpoint exists), so cap the config to bound worker time and outbound fan-out.
MAX_GEMS = 500

_HEADERS = {"Accept": "application/json"}

# Rows for a single gem are yielded in bounded chunks so a gem with a very large version history
# never forces one oversized in-memory Arrow conversion downstream. The pipeline batches on top of
# this, so the exact value only caps the per-yield list size.
MAX_ROWS_PER_BATCH = 5000

# `timeframe_versions` rejects a `from`..`to` range longer than 7 days and pages 30 versions at a time.
TIMEFRAME_MAX_WINDOW = dt.timedelta(days=7)
TIMEFRAME_PAGE_SIZE = 30
# A first sync, or one with no recorded history start, reads this far back. The feed covers every gem
# on RubyGems.org, so the whole history would take hundreds of thousands of requests.
TIMEFRAME_HISTORY_LOOKBACK = dt.timedelta(days=7)


class RubyGemsRetryableError(Exception):
    pass


def parse_gems(raw: str | None) -> list[str]:
    """Parse the user's free-text ``gems`` field into a list of gem names.

    Accepts one gem per line and/or comma-separated names. Raises ``ValueError`` with an
    actionable message on empty input so the user fixes the config rather than getting a silently
    empty sync. Names are de-duplicated while preserving order.
    """
    if not raw:
        raise ValueError("At least one gem name is required.")

    gems: list[str] = []
    seen: set[str] = set()
    for token in re.split(r"[\n,]", raw):
        name = token.strip()
        if not name:
            continue
        if name not in seen:
            seen.add(name)
            gems.append(name)

        if len(gems) > MAX_GEMS:
            raise ValueError(f"Too many gems: at most {MAX_GEMS} are allowed per source.")

    if not gems:
        raise ValueError("At least one gem name is required.")

    return gems


def _gem_url(gem: str) -> str:
    # RubyGems.org resolves the gem name as-is; percent-encode the path segment so an odd
    # character can't break out of the path.
    return f"{RUBYGEMS_BASE_URL}/gems/{quote(gem, safe='')}.json"


def _versions_url(gem: str) -> str:
    return f"{RUBYGEMS_BASE_URL}/versions/{quote(gem, safe='')}.json"


def _owners_url(gem: str) -> str:
    return f"{RUBYGEMS_BASE_URL}/gems/{quote(gem, safe='')}/owners.json"


def _reverse_dependencies_url(gem: str) -> str:
    return f"{RUBYGEMS_BASE_URL}/gems/{quote(gem, safe='')}/reverse_dependencies.json"


def _timeframe_versions_url(start: dt.datetime, end: dt.datetime, page: int) -> str:
    params = {"from": _iso8601(start), "to": _iso8601(end), "page": page}
    return f"{RUBYGEMS_BASE_URL}/timeframe_versions.json?{urlencode(params)}"


def _iso8601(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


_PER_GEM_URLS: dict[str, Callable[[str], str]] = {
    "gems": _gem_url,
    "versions": _versions_url,
    "owners": _owners_url,
    "reverse_dependencies": _reverse_dependencies_url,
}

_FEED_URLS: dict[str, str] = {
    "latest_gems": f"{RUBYGEMS_BASE_URL}/activity/latest.json",
    "just_updated_gems": f"{RUBYGEMS_BASE_URL}/activity/just_updated.json",
}


@retry_with_deadline(
    retry=retry_if_exception_type((RubyGemsRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(session: requests.Session, url: str, label: str, logger: FilteringBoundLogger) -> Any | None:
    """Fetch a single JSON document.

    Returns ``None`` for a 404 (gem not found) so a typo'd or unpublished gem is skipped rather
    than failing the whole sync. Transient 429/5xx raise a retryable error; other client errors
    raise ``requests.HTTPError``.
    """
    response = session.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 404:
        logger.warning(f"RubyGems: {label!r} not found, skipping")
        return None

    if response.status_code == 429 or response.status_code >= 500:
        raise RubyGemsRetryableError(f"RubyGems API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"RubyGems API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _gem_rows(gem: str, document: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """One row per gem: the full `/gems/{name}.json` document, stamped with the requested name."""
    row = dict(document)
    # `name` is the primary key; fall back to the requested gem if the API omits it.
    row.setdefault("name", gem)
    yield row


def _version_rows(gem: str, versions: list[Any]) -> Iterator[dict[str, Any]]:
    """One row per published version of a gem, stamped with the parent `gem_name`.

    `gem_name` completes the `[gem_name, number, platform]` primary key: version numbers repeat
    across platforms (e.g. native-extension gems publishing separate `ruby`/`java` builds) and rows
    aggregate across every configured gem.
    """
    for version in versions:
        if not isinstance(version, dict):
            continue
        # `number` and `platform` are part of the primary key; a version object missing either
        # would merge with a null key component, so skip it rather than emit an unmergeable row.
        if not version.get("number") or not version.get("platform"):
            continue
        row = dict(version)
        row["gem_name"] = gem
        yield row


def _owner_rows(gem: str, owners: list[Any]) -> Iterator[dict[str, Any]]:
    """One row per owner of a gem, stamped with the parent `gem_name`."""
    for owner in owners:
        if not isinstance(owner, dict) or owner.get("id") is None:
            continue
        row = dict(owner)
        row["gem_name"] = gem
        yield row


def _reverse_dependency_rows(gem: str, dependents: list[Any]) -> Iterator[dict[str, Any]]:
    """One row per dependent gem. The API returns bare gem names, so wrap each in a row."""
    for dependent in dependents:
        if not isinstance(dependent, str) or not dependent:
            continue
        yield {"gem_name": gem, "dependent_name": dependent}


def _keyed_rows(rows: list[Any], primary_keys: list[str]) -> list[dict[str, Any]]:
    # A row missing a primary key component would merge with a null key, so drop it.
    return [row for row in rows if isinstance(row, dict) and all(row.get(key) for key in primary_keys)]


_ROW_BUILDERS: dict[str, Callable[[str, Any], Iterator[dict[str, Any]]]] = {
    "gems": _gem_rows,
    "versions": _version_rows,
    "owners": _owner_rows,
    "reverse_dependencies": _reverse_dependency_rows,
}


def validate_credentials(gems_raw: str | None) -> tuple[bool, str | None]:
    """Confirm the config is usable by probing the first configured gem.

    RubyGems.org's read APIs are unauthenticated, so there is no key to check; instead we confirm
    at least one gem is configured and that it resolves (200). A 404 means the gem name is wrong.
    """
    try:
        gems = parse_gems(gems_raw)
    except ValueError as exc:
        return False, str(exc)

    gem = gems[0]
    try:
        response = make_tracked_session().get(_gem_url(gem), headers=_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception:
        return False, "Could not reach the RubyGems.org API. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code == 404:
        return False, f"Gem '{gem}' was not found on RubyGems.org. Check the spelling and try again."

    return False, f"RubyGems.org API returned an unexpected status code: {response.status_code}"


def get_rows(
    endpoint: str,
    gems: list[str],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    # One session reused across every gem so urllib3 keeps the connection alive.
    session = make_tracked_session()

    for gem in gems:
        document = _fetch(session, _PER_GEM_URLS[endpoint](gem), gem, logger)
        if document is None:
            continue
        if endpoint == "gems":
            source_data: Any = document
        else:
            source_data = document if isinstance(document, list) else []

        build_rows = _ROW_BUILDERS[endpoint]
        # Stream the builder into bounded chunks: a gem with a very large version history is never
        # materialized as one oversized list, and each yield caps the downstream Arrow conversion.
        # The pipeline batches on top of this.
        chunk: list[dict[str, Any]] = []
        for row in build_rows(gem, source_data):
            chunk.append(row)
            if len(chunk) >= MAX_ROWS_PER_BATCH:
                yield chunk
                chunk = []
        if chunk:
            yield chunk


def get_feed_rows(endpoint: str, logger: FilteringBoundLogger) -> Iterator[list[dict[str, Any]]]:
    document = _fetch(make_tracked_session(), _FEED_URLS[endpoint], endpoint, logger)
    rows = _keyed_rows(document if isinstance(document, list) else [], RUBYGEMS_ENDPOINTS[endpoint].primary_keys)
    if rows:
        yield rows


def get_timeframe_version_rows(
    start: dt.datetime,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Walk 7-day windows from ``start`` to now, paging each window until a short page."""
    session = make_tracked_session()
    end = dt.datetime.now(dt.UTC)
    primary_keys = RUBYGEMS_ENDPOINTS["timeframe_versions"].primary_keys

    window_start = start
    while window_start < end:
        window_end = min(window_start + TIMEFRAME_MAX_WINDOW, end)
        page = 1
        while True:
            versions = _fetch(
                session, _timeframe_versions_url(window_start, window_end, page), "timeframe_versions", logger
            )
            if not isinstance(versions, list) or not versions:
                break
            rows = _keyed_rows(versions, primary_keys)
            if rows:
                yield rows
            if len(versions) < TIMEFRAME_PAGE_SIZE:
                break
            page += 1
        window_start = window_end


def timeframe_start(
    should_use_incremental_field: bool,
    last_value: Any,
    history_start: Optional[dt.datetime],
) -> dt.datetime:
    if should_use_incremental_field and last_value is not None:
        watermark = parse_datetime_value(last_value)
        if watermark is not None:
            return watermark
    if history_start is not None:
        return history_start
    return dt.datetime.now(dt.UTC) - TIMEFRAME_HISTORY_LOOKBACK


def rubygems_source(
    endpoint: str,
    gems_raw: str | None,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    history_start: Optional[dt.datetime] = None,
) -> SourceResponse:
    config: RubyGemsEndpointConfig = RUBYGEMS_ENDPOINTS[endpoint]

    partition_kwargs: dict[str, Any] = {}
    if config.partition_key is not None:
        partition_kwargs = {
            "partition_count": 1,
            "partition_size": 1,
            "partition_mode": "datetime",
            "partition_format": "month",
            "partition_keys": [config.partition_key],
        }

    if endpoint == "timeframe_versions":
        start = timeframe_start(should_use_incremental_field, db_incremental_field_last_value, history_start)
        return SourceResponse(
            name=endpoint,
            items=lambda: get_timeframe_version_rows(start=start, logger=logger),
            primary_keys=config.primary_keys,
            # The API returns each window oldest first in practice, but does not document an order.
            sort_mode=None,
            **partition_kwargs,
        )

    gems = parse_gems(gems_raw) if config.per_gem else []

    def items() -> Iterator[list[dict[str, Any]]]:
        if config.per_gem:
            return get_rows(endpoint=endpoint, gems=gems, logger=logger)
        return get_feed_rows(endpoint=endpoint, logger=logger)

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        # No server-side ordering to rely on; rows are grouped per gem as fetched.
        sort_mode="asc",
        **partition_kwargs,
    )
