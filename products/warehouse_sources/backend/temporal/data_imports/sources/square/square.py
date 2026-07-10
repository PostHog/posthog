import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.square.settings import (
    SQUARE_ENDPOINTS,
    SquareEndpointConfig,
)

# Square pins API behaviour to a dated version header. Bump deliberately after
# re-reading the changelog — newer versions can reshape responses.
SQUARE_API_VERSION = "2024-10-17"

SQUARE_HOSTS = {
    "production": "https://connect.squareup.com",
    "sandbox": "https://connect.squareupsandbox.com",
}

# Square cursors expire ~5 minutes after they're issued, and a cursor is only spent
# once the previous page has been processed downstream. Smaller pages mean less
# per-page processing, so each cursor is far more likely to be used inside its TTL —
# the main driver of the INVALID_CURSOR failures on large streams (e.g. customers).
PAGE_SIZE = 50
REQUEST_TIMEOUT_SECONDS = 60

# A Square cursor that outlives its ~5 minute TTL mid-stream forces a restart. Allow a
# handful so a transient stall during the re-scan doesn't fail the sync, while still
# bounding the work for a stream that paginates slower than its cursor lives. Endpoints
# with a server-side time filter resume from the last value seen instead of re-scanning
# from zero (see get_rows), so this budget mostly protects the full-refresh streams.
MAX_CURSOR_RESTARTS = 5


class SquareRetryableError(Exception):
    pass


class SquareInvalidCursorError(Exception):
    pass


def _is_invalid_cursor_error(response: requests.Response) -> bool:
    """A 400 whose error payload points at the pagination cursor. Square cursors
    have a ~5 minute lifetime, so a resumed or slowly-paginated cursor can expire
    mid-stream and Square then rejects it as invalid/incompatible."""
    if response.status_code != 400:
        return False
    try:
        errors = response.json().get("errors") or []
    except ValueError:
        return False
    return any(error.get("field") == "cursor" or error.get("code") == "INVALID_CURSOR" for error in errors)


@dataclasses.dataclass
class SquareResumeConfig:
    # The next-page pagination cursor returned by Square. Square cursors expire
    # after ~5 minutes, so a resume that lands outside that window will re-fetch
    # the stream from the start (merge dedupes on the primary key).
    cursor: str


def _base_url(environment: str) -> str:
    return SQUARE_HOSTS.get(environment, SQUARE_HOSTS["production"])


def _get_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Square-Version": SQUARE_API_VERSION,
        "Accept": "application/json",
    }


def _format_rfc3339(value: Any) -> str:
    """Format an incremental value as the RFC 3339 timestamp Square expects."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return str(value)


def _build_initial_params(
    config: SquareEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, str]:
    params: dict[str, str] = dict(config.extra_params)

    if config.paginated:
        params["limit"] = str(PAGE_SIZE)

    if config.time_filter_param and should_use_incremental_field and db_incremental_field_last_value is not None:
        params[config.time_filter_param] = _format_rfc3339(db_incremental_field_last_value)

    return params


def _time_filter_field(config: SquareEndpointConfig) -> Optional[str]:
    """The record field that ``time_filter_param`` filters on, or ``None`` when the
    endpoint has no server-side time filter. Used to seed a restart from the last value
    seen so an expired cursor resumes mid-stream instead of re-scanning from the start."""
    if not config.time_filter_param or not config.incremental_fields:
        return None
    return config.incremental_fields[0]["field"]


def validate_credentials(access_token: str, environment: str, schema_name: Optional[str] = None) -> tuple[bool, bool]:
    """Probe Square to confirm the token works.

    Returns ``(is_valid, is_forbidden)``. ``is_forbidden`` distinguishes a 403
    (valid token, missing scope) from a 401 (bad token) so the caller can accept
    scope gaps at source-create time but reject them for a specific schema.
    """
    config = SQUARE_ENDPOINTS.get(schema_name) if schema_name else None
    path = config.path if config else "/v2/locations"

    # Keep the probe cheap on paginated endpoints, but never send `limit` to a
    # non-paginated endpoint (e.g. /v2/locations) — Square may reject the unknown param.
    params: dict[str, str] = {}
    if config is not None and config.paginated:
        params["limit"] = "1"

    url = f"{_base_url(environment)}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"

    try:
        response = make_tracked_session().get(url, headers=_get_headers(access_token), timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception:
        return False, False

    if response.status_code == 403:
        return False, True

    return response.status_code == 200, False


def get_rows(
    access_token: str,
    environment: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SquareResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = SQUARE_ENDPOINTS[endpoint]
    headers = _get_headers(access_token)
    url = f"{_base_url(environment)}{config.path}"

    initial_params = _build_initial_params(config, should_use_incremental_field, db_incremental_field_last_value)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor: Optional[str] = resume_config.cursor if resume_config else None
    if cursor:
        logger.debug(f"Square: resuming {endpoint} from saved cursor")

    @retry(
        retry=retry_if_exception_type((SquareRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(params: dict[str, str]) -> dict[str, Any]:
        response = make_tracked_session().get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise SquareRetryableError(f"Square API error (retryable): status={response.status_code}, url={url}")

        if _is_invalid_cursor_error(response):
            raise SquareInvalidCursorError(f"Square rejected the pagination cursor for {endpoint}")

        if not response.ok:
            logger.error(f"Square API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    # The record field the server-side time filter applies to (e.g. created_at), if any.
    # Tracked so a restart can resume from the last value seen rather than from zero.
    time_field = _time_filter_field(config)
    last_seen_value: Optional[str] = None

    restarts_remaining = MAX_CURSOR_RESTARTS
    while True:
        # Square encodes the original query in the cursor, so subsequent pages are
        # requested with the cursor alone — re-sending filters/sort can error.
        params = {"cursor": cursor} if cursor else initial_params
        try:
            data = fetch_page(params)
        except SquareInvalidCursorError:
            # An expired cursor can't be recovered by retrying it, so restart the stream
            # (merge dedupes on the primary key). A cursor-less initial request can't
            # trigger this error, so a rejection there signals a malformed query rather
            # than expiry — surface it instead of looping. The restart budget bounds the
            # work when a stream keeps outliving its cursor.
            if cursor is None or restarts_remaining <= 0:
                raise
            restarts_remaining -= 1
            cursor = None
            # On an endpoint with a server-side time filter, resume from the last value
            # we saw so the restart re-scans only the unfinished tail rather than the
            # whole stream — otherwise it just hits the same ~5 min TTL wall again.
            # Endpoints without one (e.g. customers) fall back to a full restart.
            if time_field is not None and last_seen_value is not None and config.time_filter_param is not None:
                initial_params = {**initial_params, config.time_filter_param: _format_rfc3339(last_seen_value)}
                logger.warning(f"Square: cursor for {endpoint} was rejected, resuming from last seen {time_field}")
            else:
                logger.warning(f"Square: cursor for {endpoint} was rejected, restarting stream from the beginning")
            # Overwrite the stale cursor in the resume store now. Otherwise, if the
            # restart finishes within a single page (no fresh next_cursor to save),
            # the expired cursor lingers until its TTL and every later sync re-scans
            # the whole stream. An empty cursor is falsy, so the next load resumes
            # from the start rather than replaying the bad value.
            if config.paginated:
                resumable_source_manager.save_state(SquareResumeConfig(cursor=""))
            continue

        items = data.get(config.data_key, [])
        next_cursor = data.get("cursor")

        if items:
            yield items
            # Advance the time watermark so a later cursor expiry can resume from here.
            if time_field is not None:
                for item in items:
                    value = item.get(time_field)
                    if isinstance(value, str) and (last_seen_value is None or value > last_seen_value):
                        last_seen_value = value
            # Save state only after yielding, so a crash re-yields the last batch
            # rather than skipping it (merge dedupes on the primary key). No point
            # persisting a cursor for non-paginated endpoints — there's nothing to
            # resume into.
            if config.paginated and next_cursor:
                resumable_source_manager.save_state(SquareResumeConfig(cursor=next_cursor))

        if not config.paginated or not next_cursor:
            break

        cursor = next_cursor


def square_source(
    access_token: str,
    environment: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SquareResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SQUARE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
            environment=environment,
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
    )
