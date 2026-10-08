import datetime
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.settings import (
    COINMARKETCAP_BATCH_ENDPOINTS,
    COINMARKETCAP_ENDPOINTS,
    COINMARKETCAP_SNAPSHOT_ENDPOINTS,
    HISTORICAL_BACKFILL_DAYS,
    HISTORICAL_COIN_LIMIT,
    HISTORICAL_EXCHANGE_LIMIT,
    PAGE_SIZE,
    CoinMarketCapBatchEndpointConfig,
    CoinUniverse,
    RowShape,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# All requests go to CoinMarketCap's Pro API host.
COINMARKETCAP_BASE_URL = "https://pro-api.coinmarketcap.com"

# Header CoinMarketCap recommends for passing the Pro API key (over the query-string form).
API_KEY_HEADER = "X-CMC_PRO_API_KEY"

REQUEST_TIMEOUT_SECONDS = 60


@frozen
class CoinMarketCapResumeConfig:
    # Next `start` for the offset-paginated list endpoints.
    start: int = 1
    # Highest coin id already yielded by an endpoint addressed by an explicit id list. The
    # boundary is an id rather than a batch position because the coin universe changes between
    # attempts: a coin that leaves it would shift later ids into a skipped prefix.
    last_coin_id: int = 0
    # Last UTC day (ISO date) already yielded by a day-walking snapshot endpoint.
    last_snapshot_date: str = ""


class CoinMarketCapPaginator(OffsetPaginator):
    """1-based offset/limit paginator with resume support.

    CoinMarketCap's list endpoints page on `start` (1-based) and `limit`. They don't
    return a usable total in the response, and an out-of-range `start` returns an empty
    `data` list with HTTP 200, so empty-/short-page detection is the reliable stop
    condition (`total_path=None`).
    """

    def __init__(self) -> None:
        super().__init__(
            limit=PAGE_SIZE,
            offset=1,  # `start` is 1-based; start=0 is rejected with a 400.
            offset_param="start",
            limit_param="limit",
            total_path=None,
        )

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page:
            return {"start": self.offset}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        start = state.get("start")
        if start is not None:
            self.offset = int(start)
            self._has_next_page = True


def get_resource(endpoint: str) -> EndpointResource:
    config = COINMARKETCAP_ENDPOINTS[endpoint]
    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": {
            "data_selector": config.data_selector,
            "path": config.path,
            "params": dict(config.extra_params),
        },
        "table_format": "delta",
    }


def _api_session(api_key: str) -> requests.Session:
    return make_tracked_session(
        headers={API_KEY_HEADER: api_key},
        redact_values=(api_key,),
        # No legitimate redirect to follow, so pinning it off keeps traffic on the validated host.
        allow_redirects=False,
    )


def _get(session: requests.Session, path: str, params: dict[str, Any]) -> dict[str, Any]:
    response = session.get(f"{COINMARKETCAP_BASE_URL}{path}", params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    body = response.json()
    return body if isinstance(body, dict) else {}


def _ids_from_map(session: requests.Session, path: str) -> list[int]:
    ids: list[int] = []
    start = 1
    while True:
        page = _get(session, path, {"start": start, "limit": PAGE_SIZE, "sort": "id"})
        rows = page.get("data") or []
        ids.extend(int(row["id"]) for row in rows if isinstance(row, dict) and row.get("id") is not None)
        # Counted before filtering: an unusable row on a full page must not end the walk.
        if len(rows) < PAGE_SIZE:
            return ids
        start += PAGE_SIZE


def _top_ids_by_rank(session: requests.Session, path: str, sort: str, limit: int) -> list[int]:
    page = _get(session, path, {"start": 1, "limit": limit, "sort": sort, "sort_dir": "desc"})
    rows = [row for row in (page.get("data") or []) if isinstance(row, dict) and row.get("id") is not None]
    # Sorted by id rather than left in rank order, so a resumed run batches the same ids in the
    # same order as the run it picks up from even though the ranking itself moves between syncs.
    return sorted(int(row["id"]) for row in rows)


def _universe_ids(session: requests.Session, universe: CoinUniverse) -> list[int]:
    if universe == "map":
        return _ids_from_map(session, "/v1/cryptocurrency/map")
    if universe == "exchange_map":
        return _ids_from_map(session, "/v1/exchange/map")
    if universe == "top_by_market_cap":
        return _top_ids_by_rank(session, "/v1/cryptocurrency/listings/latest", "market_cap", HISTORICAL_COIN_LIMIT)
    return _top_ids_by_rank(session, "/v1/exchange/listings/latest", "volume_24h", HISTORICAL_EXCHANGE_LIMIT)


def _coin_entries(data: Any) -> Iterator[dict[str, Any]]:
    """Yield each cryptocurrency or exchange object out of a CoinMarketCap `data` payload.

    Requesting several ids returns a map keyed by id, a single id returns the object on its own,
    and requesting by symbol wraps each value in a list.
    """
    if isinstance(data, dict) and "id" in data:
        yield data
        return
    values = list(data.values()) if isinstance(data, dict) else data if isinstance(data, list) else []
    for value in values:
        if isinstance(value, list):
            yield from (item for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            yield value


def _rows_from(row_shape: RowShape, data: Any) -> list[dict[str, Any]]:
    if row_shape == "quote_list":
        quotes = data.get("quotes") if isinstance(data, dict) else None
        return [quote for quote in (quotes or []) if isinstance(quote, dict)]

    if row_shape == "per_coin_quotes":
        rows: list[dict[str, Any]] = []
        for entry in _coin_entries(data):
            identity = {key: value for key, value in entry.items() if key != "quotes"}
            rows.extend({**identity, **quote} for quote in (entry.get("quotes") or []) if isinstance(quote, dict))
        return rows

    return list(_coin_entries(data))


def _history_start(db_incremental_field_last_value: Optional[Any]) -> str:
    if isinstance(db_incremental_field_last_value, datetime.datetime | datetime.date):
        return db_incremental_field_last_value.isoformat()
    if isinstance(db_incremental_field_last_value, str) and db_incremental_field_last_value:
        return db_incremental_field_last_value
    backfill_start = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=HISTORICAL_BACKFILL_DAYS)
    return backfill_start.date().isoformat()


def get_batch_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CoinMarketCapResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> Iterator[list[dict[str, Any]]]:
    config = COINMARKETCAP_BATCH_ENDPOINTS[endpoint]
    session = _api_session(api_key)

    params: dict[str, Any] = dict(config.extra_params)
    if config.windowed:
        params["time_start"] = _history_start(db_incremental_field_last_value)

    if config.universe is None:
        rows = _rows_from(config.row_shape, _get(session, config.path, params).get("data"))
        if rows:
            yield rows
        return

    coin_ids = _universe_ids(session, config.universe)
    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    last_coin_id = resume_config.last_coin_id if resume_config is not None else 0
    if last_coin_id:
        logger.debug(f"CoinMarketCap: resuming {endpoint} after coin id {last_coin_id}")
        coin_ids = [coin_id for coin_id in coin_ids if coin_id > last_coin_id]

    for index in range(0, len(coin_ids), config.batch_size):
        batch = coin_ids[index : index + config.batch_size]
        body = _get(session, config.path, {**params, "id": ",".join(str(coin_id) for coin_id in batch)})
        rows = _rows_from(config.row_shape, body.get("data"))
        if rows:
            yield rows

        # Saved after the batch is yielded, so a crash re-yields it rather than skipping it;
        # the merge de-duplicates on the endpoint's primary key.
        resumable_source_manager.save_state(CoinMarketCapResumeConfig(last_coin_id=batch[-1]))


def _batch_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CoinMarketCapResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    config: CoinMarketCapBatchEndpointConfig = COINMARKETCAP_BATCH_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_batch_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=list(config.primary_keys),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # A per-coin endpoint restarts at the window's earliest point for every batch of coins,
        # so only the single global-metrics series arrives in ascending order.
        sort_mode="asc" if config.universe is None else None,
    )


def _last_published_snapshot_date(now: datetime.datetime) -> datetime.date:
    """Most recent UTC day whose ranked snapshot CoinMarketCap has published.

    A completed day's snapshot lands about 30 minutes after midnight, so for the first hour of a
    new day the newest day on offer is the one before yesterday. Asking for a day CoinMarketCap
    has not published yet would fail the sync once a day, on the hour it rolls over.
    """
    yesterday = now.date() - datetime.timedelta(days=1)
    return yesterday if now.hour >= 1 else yesterday - datetime.timedelta(days=1)


def _snapshot_start_date(db_incremental_field_last_value: Optional[Any]) -> datetime.date:
    if isinstance(db_incremental_field_last_value, datetime.datetime):
        return db_incremental_field_last_value.date()
    if isinstance(db_incremental_field_last_value, datetime.date):
        return db_incremental_field_last_value
    if isinstance(db_incremental_field_last_value, str) and db_incremental_field_last_value:
        try:
            return datetime.date.fromisoformat(db_incremental_field_last_value[:10])
        except ValueError:
            pass
    backfill_start = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=HISTORICAL_BACKFILL_DAYS)
    return backfill_start.date()


def get_snapshot_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CoinMarketCapResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> Iterator[list[dict[str, Any]]]:
    config = COINMARKETCAP_SNAPSHOT_ENDPOINTS[endpoint]
    session = _api_session(api_key)

    # The watermark day is re-requested rather than stepped over: a run cut short part-way through
    # a day would otherwise leave the rest of that day's ranking missing for good. One day costs a
    # single credit and the merge de-duplicates the overlap.
    day = _snapshot_start_date(db_incremental_field_last_value)
    last_day = _last_published_snapshot_date(datetime.datetime.now(datetime.UTC))

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None and resume_config.last_snapshot_date:
        logger.debug(f"CoinMarketCap: resuming {endpoint} after {resume_config.last_snapshot_date}")
        resumed_day = datetime.date.fromisoformat(resume_config.last_snapshot_date) + datetime.timedelta(days=1)
        day = max(day, resumed_day)

    while day <= last_day:
        body = _get(
            session,
            config.path,
            {**config.extra_params, "date": day.isoformat(), "start": 1, "limit": config.limit},
        )
        rows = [row for row in (body.get("data") or []) if isinstance(row, dict)]
        if rows:
            yield [{**row, config.date_field: day.isoformat()} for row in rows]

        # Saved after the day is yielded, so a crash re-yields that day rather than skipping it.
        resumable_source_manager.save_state(CoinMarketCapResumeConfig(last_snapshot_date=day.isoformat()))
        day += datetime.timedelta(days=1)


def _snapshot_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CoinMarketCapResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    config = COINMARKETCAP_SNAPSHOT_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_snapshot_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=list(config.primary_keys),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # One request per day, walked oldest day first.
        sort_mode="asc",
    )


def coinmarketcap_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CoinMarketCapResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    if endpoint in COINMARKETCAP_SNAPSHOT_ENDPOINTS:
        return _snapshot_source(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )

    if endpoint in COINMARKETCAP_BATCH_ENDPOINTS:
        return _batch_source(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )

    endpoint_config = COINMARKETCAP_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": COINMARKETCAP_BASE_URL,
            # Going through APIKeyAuth (rather than raw headers) registers the key
            # for value-based log redaction.
            "auth": {
                "type": "api_key",
                "api_key": api_key,
                "name": API_KEY_HEADER,
                "location": "header",
            },
            "paginator": CoinMarketCapPaginator(),
            # CoinMarketCap's API responds directly, so there's no legitimate redirect
            # to follow; pinning it off keeps traffic on the validated host.
            "session": make_tracked_session(redact_values=(api_key,), allow_redirects=False),
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": [get_resource(endpoint)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"start": resume_config.start}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when there's a next page to resume to; the Redis TTL handles
        # cleanup once the sync finishes. Saving happens after each page is yielded,
        # so a crash re-fetches the last page rather than skipping it.
        if state and state.get("start") is not None:
            resumable_source_manager.save_state(CoinMarketCapResumeConfig(start=int(state["start"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        sort_mode="asc",
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Probe the zero-credit `/v1/key/info` endpoint to confirm the key is genuine.

    Returns (is_valid, error_message). A 200 means the key authenticates; 401 means it's
    missing or invalid. Any other status / network error is surfaced verbatim.
    """
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{COINMARKETCAP_BASE_URL}/v1/key/info",
            headers={API_KEY_HEADER: api_key},
            timeout=10,
            allow_redirects=False,
        )
    except Exception as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid CoinMarketCap API key"
    return False, f"CoinMarketCap returned an unexpected status code: {response.status_code}"
