import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urljoin, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.teamcity.settings import (
    FAN_OUT_BUILD_FINISH_DATE_FIELD,
    FAN_OUT_BUILD_ID_FIELD,
    MAX_PAGES_PER_BUILD,
    TEAMCITY_ENDPOINTS,
    TeamCityEndpointConfig,
)

TEAMCITY_API_PATH = "/app/rest"

# TeamCity's compact ISO-8601 timestamp format, e.g. "20260715T160948+0000".
TEAMCITY_DATETIME_FORMAT = "%Y%m%dT%H%M%S%z"

# Slim parent payload for the occurrence fan-out: only the fields the fan-out itself needs.
FAN_OUT_PARENT_FIELDS = "count,nextHref,build(id,finishDate)"

REQUEST_TIMEOUT_SECONDS = 60


class TeamCityRetryableError(Exception):
    pass


@dataclasses.dataclass
class TeamCityResumeConfig:
    # Server-relative nextHref of the next page to fetch (for fan-out endpoints, the next
    # page of the parent builds walk). None means "start from the first page".
    next_href: str | None = None


def normalize_host(host: str) -> str:
    """Reduce user input to a validated TeamCity server root URL.

    Accepts "https://teamcity.example.com", a bare host, or a URL with a context path
    (TeamCity is often served under one, e.g. "https://ci.example.com/teamcity"), with or
    without a trailing "/app/rest". Raises ``ValueError`` on anything that could retarget
    the stored token (userinfo, query, fragment) or that isn't a plain http(s) URL.
    """
    cleaned = host.strip().rstrip("/")
    if not cleaned:
        raise ValueError("TeamCity server URL is required")
    if "://" not in cleaned:
        cleaned = f"https://{cleaned}"

    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Invalid TeamCity server URL: {host!r}. Use an http(s) URL.")
    if not parsed.hostname:
        raise ValueError(
            f"Invalid TeamCity server URL: {host!r}. Enter your server URL, e.g. https://teamcity.example.com."
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(
            f"Invalid TeamCity server URL: {host!r}. Enter just the server URL, without credentials or query parameters."
        )

    path = parsed.path.rstrip("/")
    if path.endswith(TEAMCITY_API_PATH):
        path = path[: -len(TEAMCITY_API_PATH)]

    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _server_root(host: str) -> str:
    """Scheme + netloc only — nextHref values are server-relative and already carry any context path."""
    parsed = urlparse(normalize_host(host))
    return f"{parsed.scheme}://{parsed.netloc}"


def _api_base(host: str) -> str:
    return f"{normalize_host(host)}{TEAMCITY_API_PATH}"


def _headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}


def _check_host_safe(host: str, team_id: int) -> None:
    hostname = urlparse(normalize_host(host)).hostname or ""
    is_safe, error = _is_host_safe(hostname, team_id)
    if not is_safe:
        raise ValueError(f"Invalid TeamCity server URL: {error}")


def _format_teamcity_datetime(value: Any) -> str:
    """Format an incremental cursor as the compact ISO-8601 string TeamCity locators expect."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime(TEAMCITY_DATETIME_FORMAT)
    return str(value)


def _parse_teamcity_datetime(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return datetime.strptime(value, TEAMCITY_DATETIME_FORMAT)
        except ValueError:
            return value
    return value


def _normalize_row(row: dict[str, Any], timestamp_fields: list[str]) -> dict[str, Any]:
    for timestamp_field in timestamp_fields:
        if timestamp_field in row:
            row[timestamp_field] = _parse_teamcity_datetime(row[timestamp_field])
    return row


def _build_locator(dimensions: dict[str, str]) -> str:
    return ",".join(f"{name}:{value}" for name, value in dimensions.items())


def _incremental_locator_dimensions(
    config: TeamCityEndpointConfig,
    db_incremental_field_last_value: Any,
) -> dict[str, str]:
    """Server-side incremental filter dimensions for an endpoint's locator.

    Verified against a live server: both filters are honored (a future-dated/too-high
    cursor returns 0 rows) and are preserved in nextHref, so every page stays windowed.
    """
    if db_incremental_field_last_value is None:
        return {}
    if config.name == "changes":
        return {"sinceChange": f"(id:{int(db_incremental_field_last_value)})"}
    # builds, and the parent walk of the occurrence fan-outs
    return {"finishDate": f"(date:{_format_teamcity_datetime(db_incremental_field_last_value)},condition:after)"}


def _build_list_url(
    api_base: str,
    path: str,
    locator_dimensions: dict[str, str],
    fields: str,
) -> str:
    params = {"locator": _build_locator(locator_dimensions), "fields": fields}
    return f"{api_base}{path}?{urlencode(params)}"


@retry(
    retry=retry_if_exception_type((TeamCityRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    # Throughput is bounded by the customer's own server; back off on 429 and transient 5xx
    # rather than failing the sync.
    if response.status_code == 429 or response.status_code >= 500:
        raise TeamCityRetryableError(f"TeamCity API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"TeamCity API error: status={response.status_code}, body={response.text[:500]}, url={url}")
        response.raise_for_status()

    return response.json()


def _paginate(
    session: requests.Session,
    server_root: str,
    first_url: str,
    headers: dict[str, str],
    response_key: str,
    logger: FilteringBoundLogger,
) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
    """Yield ``(items, next_href)`` per page, following TeamCity's nextHref cursor."""
    url = first_url
    while True:
        data = _fetch_page(session, url, headers, logger)
        next_href = data.get("nextHref")
        yield data.get(response_key, []), next_href
        if not next_href:
            return
        url = urljoin(server_root, next_href)


def _top_level_rows(
    session: requests.Session,
    host: str,
    headers: dict[str, str],
    config: TeamCityEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TeamCityResumeConfig],
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    server_root = _server_root(host)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_href:
        logger.debug(f"TeamCity: resuming {config.name} from {resume.next_href}")
        first_url = urljoin(server_root, resume.next_href)
    else:
        locator_dimensions = {
            **config.locator_defaults,
            **_incremental_locator_dimensions(config, db_incremental_field_last_value),
            "count": str(config.page_size),
        }
        first_url = _build_list_url(_api_base(host), config.path, locator_dimensions, config.fields)

    for items, next_href in _paginate(session, server_root, first_url, headers, config.response_key, logger):
        if items:
            yield [_normalize_row(item, config.timestamp_fields) for item in items]
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it —
        # merge dedupes on the primary key.
        if next_href:
            resumable_source_manager.save_state(TeamCityResumeConfig(next_href=next_href))


def _occurrence_rows_for_build(
    session: requests.Session,
    host: str,
    headers: dict[str, str],
    config: TeamCityEndpointConfig,
    build: dict[str, Any],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    build_id = build["id"]
    build_finish_date = _parse_teamcity_datetime(build.get("finishDate"))
    locator_dimensions = {"build": f"(id:{build_id})", "count": str(config.page_size)}
    first_url = _build_list_url(_api_base(host), config.path, locator_dimensions, config.fields)

    pages = 0
    for items, next_href in _paginate(session, _server_root(host), first_url, headers, config.response_key, logger):
        if items:
            for item in items:
                item[FAN_OUT_BUILD_ID_FIELD] = build_id
                item[FAN_OUT_BUILD_FINISH_DATE_FIELD] = build_finish_date
            yield items

        pages += 1
        if next_href and pages >= MAX_PAGES_PER_BUILD:
            logger.warning(
                f"TeamCity: page cap reached for {config.name}, truncating fan-out. "
                f"build_id={build_id}, pages={pages}, page_size={config.page_size}"
            )
            return
        if not next_href:
            return


def _fan_out_rows(
    session: requests.Session,
    host: str,
    headers: dict[str, str],
    config: TeamCityEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TeamCityResumeConfig],
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    builds_config = TEAMCITY_ENDPOINTS["builds"]
    server_root = _server_root(host)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_href:
        logger.debug(f"TeamCity: resuming {config.name} fan-out from parent page {resume.next_href}")
        first_url = urljoin(server_root, resume.next_href)
    else:
        locator_dimensions = {
            **builds_config.locator_defaults,
            **_incremental_locator_dimensions(builds_config, db_incremental_field_last_value),
            "count": str(builds_config.page_size),
        }
        first_url = _build_list_url(_api_base(host), builds_config.path, locator_dimensions, FAN_OUT_PARENT_FIELDS)

    for builds, next_href in _paginate(session, server_root, first_url, headers, builds_config.response_key, logger):
        for build in builds:
            yield from _occurrence_rows_for_build(session, host, headers, config, build, logger)
        # Checkpoint at parent-page granularity, after every child of the page has been
        # yielded: a resume re-fans the interrupted page at worst, and merge dedupes.
        if next_href:
            resumable_source_manager.save_state(TeamCityResumeConfig(next_href=next_href))


def get_rows(
    host: str,
    access_token: str,
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TeamCityResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = TEAMCITY_ENDPOINTS[endpoint]
    _check_host_safe(host, team_id)
    session = make_tracked_session()
    headers = _headers(access_token)

    cursor = db_incremental_field_last_value if config.supports_incremental and should_use_incremental_field else None

    if config.fan_out_over_builds:
        yield from _fan_out_rows(session, host, headers, config, logger, resumable_source_manager, cursor)
    else:
        yield from _top_level_rows(session, host, headers, config, logger, resumable_source_manager, cursor)


def teamcity_source(
    host: str,
    access_token: str,
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TeamCityResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = TEAMCITY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            host=host,
            access_token=access_token,
            endpoint=endpoint,
            team_id=team_id,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        sort_mode=config.sort_mode,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(host: str, access_token: str, team_id: int) -> tuple[bool, int | None]:
    """Probe TeamCity's `/app/rest/server` endpoint to confirm the token is genuine.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error. Raises
    ``ValueError`` if the host is malformed or unsafe so the caller can surface a precise
    message.
    """
    _check_host_safe(host, team_id)
    url = f"{_api_base(host)}/server"
    try:
        response = make_tracked_session().get(url, headers=_headers(access_token), timeout=10)
    except Exception:
        return False, None
    return response.status_code == 200, response.status_code
