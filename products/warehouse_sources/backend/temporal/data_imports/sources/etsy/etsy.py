import time
import dataclasses
from collections import deque
from collections.abc import Iterator
from typing import Any, Optional

import structlog
from requests import Response
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.etsy.settings import (
    ETSY_ENDPOINTS,
    LISTING_STATES,
    EtsyEndpointConfig,
)

ETSY_API_BASE = "https://api.etsy.com/v3/application"
ETSY_TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"

# Etsy caps list pages at 100 rows and rejects an offset above 12,000.
PAGE_SIZE = 100
MAX_OFFSET = 12_000
# Walk history in 90-day slices, halving a slice that holds more rows than the offset ceiling can
# reach. One hour is the floor — below that the request count stops being worth it.
DEFAULT_WINDOW_SECONDS = 90 * 24 * 60 * 60
MIN_WINDOW_SECONDS = 60 * 60
# Etsy opened in 2005, so nothing predates this.
ETSY_HISTORY_START = 1104537600  # 2005-01-01T00:00:00Z
REQUEST_TIMEOUT_SECONDS = 60


NO_SHOP_ERROR = (
    "This Etsy account has no shop. Enter the shop ID you want to sync, or connect an account that owns a shop."
)
INVALID_SHOP_ID_ERROR = "The Etsy shop ID must be a positive number. Leave it blank to use the token's own shop."


class EtsyAPIError(Exception):
    """An Etsy request failed in a way the caller cannot recover from."""


def _validate_shop_id(shop_id: str) -> str:
    """Etsy shop IDs are positive integers. Reject anything else before it reaches the URL."""
    if not shop_id.isdigit() or int(shop_id) <= 0:
        raise EtsyAPIError(INVALID_SHOP_ID_ERROR)
    return shop_id


@dataclasses.dataclass
class EtsyResumeConfig:
    """Where a resumed run picks the walk back up.

    ``window_start``/``window_end`` pin the exact (possibly subdivided) time slice in flight, so a
    resume finishes that slice and then continues generating slices from ``window_end + 1``.
    ``listing_state`` does the same for the state fan-out on listings.
    """

    offset: int = 0
    window_start: Optional[int] = None
    window_end: Optional[int] = None
    listing_state: Optional[str] = None


class EtsyClient:
    """Etsy Open API v3 transport: x-api-key on every call plus a bearer minted from a refresh token.

    Etsy's OAuth2 uses PKCE, so the refresh exchange takes the app's keystring as ``client_id`` and
    carries no client secret. Access tokens last an hour, which a backfill routinely outlives, so a
    401 re-mints once and replays the request.
    """

    def __init__(self, api_key: str, refresh_token: str, logger: FilteringBoundLogger) -> None:
        self._api_key = api_key
        self._refresh_token = refresh_token
        self._logger = logger
        self._access_token: Optional[str] = None
        self._session = make_tracked_session(
            headers={"x-api-key": api_key, "Accept": "application/json"},
            redact_values=(api_key, refresh_token),
            # The keystring rides a custom header, which requests does not strip across a redirect.
            allow_redirects=False,
        )

    def _mint_token(self) -> str:
        response = self._session.post(
            ETSY_TOKEN_URL,
            json={
                "grant_type": "refresh_token",
                "client_id": self._api_key,
                "refresh_token": self._refresh_token,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise EtsyAPIError("Etsy returned no access token for the refresh token")
        return str(token)

    def _send(self, path: str, params: Optional[dict[str, Any]]) -> Response:
        return self._session.get(
            f"{ETSY_API_BASE}{path}",
            params=params,
            headers={"Authorization": f"Bearer {self._access_token}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    def request(self, path: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        if self._access_token is None:
            self._access_token = self._mint_token()

        response = self._send(path, params)
        if response.status_code == 401:
            self._access_token = self._mint_token()
            response = self._send(path, params)

        if response.status_code >= 300:
            self._logger.error(f"Etsy API error: status={response.status_code}, path={path}")
            response.raise_for_status()
            raise EtsyAPIError(f"Unexpected Etsy redirect response: status={response.status_code}, path={path}")

        body = response.json()
        if not isinstance(body, dict):
            raise EtsyAPIError(f"Unexpected Etsy response body for {path}: expected an object")
        return body

    def resolve_shop_id(self, configured_shop_id: Optional[str]) -> str:
        if configured_shop_id and configured_shop_id.strip():
            # Etsy shop IDs are positive integers. Reject anything else so a configured value can't
            # smuggle path segments into `/shops/{shop_id}` and retarget the authenticated request.
            return _validate_shop_id(configured_shop_id.strip())

        shop_id = self.request("/users/me").get("shop_id")
        if shop_id is None:
            raise EtsyAPIError(NO_SHOP_ERROR)
        return str(shop_id)


def validate_credentials(api_key: str, refresh_token: str, shop_id: Optional[str]) -> tuple[bool, Optional[str]]:
    """Cheap probe: mint a token and read the token's own identity.

    Always hits `/users/me`, even with a shop ID configured — otherwise a bogus keystring or refresh
    token would sail through source creation. Never raises: a probe must not block create.
    """
    if shop_id and shop_id.strip():
        try:
            _validate_shop_id(shop_id.strip())
        except EtsyAPIError as error:
            return False, str(error)

    try:
        # No job logger exists on the create-time probe path, so use the module logger.
        client = EtsyClient(api_key, refresh_token, structlog.get_logger(__name__))
        identity = client.request("/users/me")
    except Exception:
        return False, "Could not authenticate with Etsy. Check your API keystring and refresh token."

    if not (shop_id and shop_id.strip()) and identity.get("shop_id") is None:
        return False, NO_SHOP_ERROR
    return True, None


def _rows_from_results(results: list[Any], config: EtsyEndpointConfig) -> list[dict[str, Any]]:
    """Flatten a page of results, expanding the nested child list when the endpoint is derived."""
    if config.expand_key is None:
        return [row for row in results if isinstance(row, dict)]

    rows: list[dict[str, Any]] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        rows.extend(child for child in (row.get(config.expand_key) or []) if isinstance(child, dict))
    return rows


def _fetch_page(
    client: EtsyClient, path: str, params: dict[str, Any], offset: int, config: EtsyEndpointConfig
) -> tuple[list[dict[str, Any]], int, int]:
    """One offset page. Returns (rows, raw result count on the page, total rows matching the query)."""
    body = client.request(path, {**params, "limit": PAGE_SIZE, "offset": offset})
    results = body.get("results") or []
    total = int(body.get("count") or 0)
    return _rows_from_results(results, config), len(results), total


def _windowed_pages(
    client: EtsyClient,
    path: str,
    config: EtsyEndpointConfig,
    window_param: str,
    start: int,
    end: int,
    manager: ResumableSourceManager[EtsyResumeConfig],
    resume: Optional[EtsyResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Walk `start`..`end` in time slices, offset-paging each one.

    Etsy's 12,000 offset ceiling means a slice holding more rows than that can never be read to the
    end, so an oversized slice is halved (down to `MIN_WINDOW_SECONDS`) and retried instead.
    """
    pending: deque[tuple[int, int]] = deque()
    cursor = start
    offset = 0

    if resume is not None and resume.window_start is not None and resume.window_end is not None:
        pending.append((resume.window_start, resume.window_end))
        cursor = resume.window_end + 1
        offset = resume.offset

    while pending or cursor <= end:
        if pending:
            window_start, window_end = pending.popleft()
        else:
            window_start = cursor
            window_end = min(cursor + DEFAULT_WINDOW_SECONDS - 1, end)
            cursor = window_end + 1

        params = {
            **config.extra_params,
            f"min_{window_param}": window_start,
            f"max_{window_param}": window_end,
        }

        while True:
            rows, page_size, total = _fetch_page(client, path, params, offset, config)

            if offset == 0 and total > MAX_OFFSET and (window_end - window_start) >= MIN_WINDOW_SECONDS:
                midpoint = window_start + (window_end - window_start) // 2
                pending.appendleft((midpoint + 1, window_end))
                pending.appendleft((window_start, midpoint))
                break

            if rows:
                yield rows
            offset += page_size
            # Saved after the yield so a crash replays the last page (merge dedupes) instead of
            # skipping it.
            manager.save_state(EtsyResumeConfig(offset=offset, window_start=window_start, window_end=window_end))

            if page_size == 0 or page_size < PAGE_SIZE or offset >= total:
                offset = 0
                break
            if offset > MAX_OFFSET:
                logger.warning(
                    f"Etsy offset ceiling reached for {config.name} between {window_start} and {window_end}; "
                    f"{total - offset} rows in this window were not read"
                )
                offset = 0
                break


def _offset_pages(
    client: EtsyClient,
    path: str,
    config: EtsyEndpointConfig,
    manager: ResumableSourceManager[EtsyResumeConfig],
    resume: Optional[EtsyResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Offset-page an endpoint with no time filter, optionally once per listing state."""
    states: tuple[Optional[str], ...] = LISTING_STATES if config.fan_out_listing_states else (None,)
    # State written by the windowed walk is meaningless here, so only a windowless checkpoint resumes.
    resumable = resume if resume is not None and resume.window_start is None else None
    offset = resumable.offset if resumable is not None else 0

    if resumable is not None and resumable.listing_state is not None and resumable.listing_state in states:
        states = states[states.index(resumable.listing_state) :]

    for index, state in enumerate(states):
        if index > 0:
            offset = 0
        params: dict[str, Any] = dict(config.extra_params)
        if state is not None:
            params["state"] = state

        while True:
            rows, page_size, total = _fetch_page(client, path, params, offset, config)
            if rows:
                yield rows
            offset += page_size
            manager.save_state(EtsyResumeConfig(offset=offset, listing_state=state))

            if page_size == 0 or page_size < PAGE_SIZE or offset >= total:
                break
            if offset > MAX_OFFSET:
                logger.warning(
                    f"Etsy offset ceiling reached for {config.name} (state={state}); "
                    f"{total - offset} rows were not read"
                )
                break


def get_rows(
    api_key: str,
    refresh_token: str,
    shop_id: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[EtsyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> Iterator[list[dict[str, Any]]]:
    config = ETSY_ENDPOINTS[endpoint]
    client = EtsyClient(api_key, refresh_token, logger)
    path = f"/shops/{client.resolve_shop_id(shop_id)}{config.path}"

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.single_object:
        yield [client.request(path)]
    elif not config.paginated:
        rows = _rows_from_results(client.request(path).get("results") or [], config)
        if rows:
            yield rows
    else:
        window_param = _resolve_window_param(config, should_use_incremental_field, incremental_field)
        if window_param is None:
            yield from _offset_pages(client, path, config, resumable_source_manager, resume, logger)
        else:
            start = _window_start(should_use_incremental_field, db_incremental_field_last_value)
            yield from _windowed_pages(
                client,
                path,
                config,
                window_param,
                start,
                int(time.time()),
                resumable_source_manager,
                resume,
                logger,
            )

    # The walk finished, so a later attempt must start clean rather than resume mid-stream.
    resumable_source_manager.clear_state()


def _resolve_window_param(
    config: EtsyEndpointConfig, should_use_incremental_field: bool, incremental_field: Optional[str]
) -> Optional[str]:
    if should_use_incremental_field and incremental_field:
        # An unknown cursor field would silently window on the wrong column, so fall back to the
        # endpoint's own default rather than guessing.
        return config.window_params.get(incremental_field) or config.default_window_param
    return config.default_window_param


def _window_start(should_use_incremental_field: bool, db_incremental_field_last_value: Optional[Any]) -> int:
    if not should_use_incremental_field or db_incremental_field_last_value is None:
        return ETSY_HISTORY_START
    try:
        return max(int(db_incremental_field_last_value), ETSY_HISTORY_START)
    except (TypeError, ValueError):
        return ETSY_HISTORY_START


def etsy_source(
    api_key: str,
    refresh_token: str,
    shop_id: Optional[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[EtsyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config = ETSY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            refresh_token=refresh_token,
            shop_id=shop_id,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        # Slices are walked oldest-first, but Etsy documents no ordering *within* a page, so a
        # per-batch watermark could jump past rows still to come in the same slice. "desc" defers
        # the watermark write to the end of a successful run, which is the safe reading here.
        sort_mode="desc",
    )
