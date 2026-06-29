import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.coin_api.settings import (
    COIN_API_ENDPOINTS,
    CoinApiEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# CoinAPI serves all REST market data from a single host. The key rides in the `X-CoinAPI-Key` header.
#
# NOTE: response shapes, the ascending time ordering of the history endpoints, and that `time_start`
# filters server-side are taken from the public CoinAPI v1 docs and Airbyte's CoinAPI connector. CoinAPI
# no longer offers a free tier, so these could not be re-verified with a live curl smoke test — the
# pagination/merge logic is kept conservative (boundary re-fetch deduped on the primary key) to stay
# safe if the ordering ever differs from documented.
BASE_URL = "https://rest.coinapi.io"

# CoinAPI's time-series endpoints accept up to 100000 rows per request. We request a large page to
# keep the request (and billing — each 100 output items is one request) count down while staying
# comfortably under the limit.
PAGE_LIMIT = 10000
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 6
# How far back the first sync of a time-series table reaches when the user leaves `start_date` blank.
DEFAULT_LOOKBACK_DAYS = 365


class CoinApiRetryableError(Exception):
    pass


@dataclasses.dataclass
class CoinApiResumeConfig:
    # Next `time_start` (ISO 8601) to request for time-series endpoints. None for the
    # single-response reference/snapshot endpoints, which aren't resumable mid-table.
    time_start: str | None = None


def _headers(api_key: str) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["X-CoinAPI-Key"] = api_key
    return headers


def _build_url(path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{BASE_URL}{path}"
    return f"{BASE_URL}{path}?{urlencode(params)}"


def _format_time(value: Any) -> str:
    """Format an incremental cursor value as an ISO 8601 string CoinAPI accepts for `time_start`."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat().replace("+00:00", "Z")
    return str(value)


def _fetch(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> Any:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    # CoinAPI returns 429 when the daily credit or concurrency limit is hit, and may include a
    # Retry-After header. Both 429 and transient 5xx are safe to retry.
    if response.status_code == 429 or response.status_code >= 500:
        raise CoinApiRetryableError(f"CoinAPI error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"CoinAPI error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> bool:
    """Confirm the key is genuine with one cheap request. A valid key returns 200; an invalid or
    malformed key returns 401."""
    url = _build_url("/v1/exchangerate/BTC/USD", {})
    try:
        session = make_tracked_session(redact_values=(api_key,) if api_key else ())
        response = session.get(url, headers=_headers(api_key), timeout=10)
        # A valid key with a plan that gates this endpoint returns 403 — the key itself is genuine,
        # so accept it at source-create and let per-table sync surface any real access problem.
        return response.status_code in (200, 403)
    except Exception:
        return False


def _initial_time_start(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    start_date: str,
) -> str:
    if should_use_incremental_field and db_incremental_field_last_value:
        return _format_time(db_incremental_field_last_value)
    if start_date:
        return start_date
    return _format_time(datetime.now(UTC) - timedelta(days=DEFAULT_LOOKBACK_DAYS))


def _get_timeseries_rows(
    config: CoinApiEndpointConfig,
    logger: FilteringBoundLogger,
    fetch: Any,
    symbol_id: str,
    period_id: str,
    incremental_field: str,
    initial_time_start: str,
    resumable_source_manager: ResumableSourceManager[CoinApiResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    time_start = resume.time_start if resume is not None and resume.time_start else initial_time_start
    if resume is not None and resume.time_start:
        logger.debug(f"CoinAPI: resuming {config.name} from time_start={time_start}")

    path = config.path.replace("{symbol_id}", symbol_id)

    while True:
        params: dict[str, Any] = {"time_start": time_start, "limit": PAGE_LIMIT}
        if config.needs_period:
            params["period_id"] = period_id

        data = fetch(_build_url(path, params))
        if not isinstance(data, list) or not data:
            break

        # OHLCV rows omit the symbol/period they belong to; injecting them keeps the primary key
        # columns present and the table self-describing.
        for row in data:
            row["symbol_id"] = symbol_id
            if config.needs_period:
                row["period_id"] = period_id

        yield data

        # A short page is the last page.
        if len(data) < PAGE_LIMIT:
            break

        next_time_start = _format_time(data[-1][incremental_field])
        # `time_start` is inclusive, so the boundary row is re-fetched and deduped on merge. If a full
        # page shares one timestamp (e.g. a microsecond burst of trades), advancing wouldn't progress —
        # stop rather than loop forever. ISO 8601 strings in CoinAPI's fixed format compare chronologically.
        if next_time_start <= time_start:
            logger.warning(
                f"CoinAPI: {config.name} page boundary did not advance past time_start={time_start}; stopping"
            )
            break

        time_start = next_time_start
        # Save AFTER yielding so a crash re-yields the last page (deduped on the primary key) rather
        # than skipping it.
        resumable_source_manager.save_state(CoinApiResumeConfig(time_start=time_start))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CoinApiResumeConfig],
    symbol_id: str = "",
    period_id: str = "1DAY",
    exchange_rate_base_asset: str = "USD",
    start_date: str = "",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = COIN_API_ENDPOINTS[endpoint]
    session = make_tracked_session(redact_values=(api_key,) if api_key else ())
    headers = _headers(api_key)

    @retry(
        retry=retry_if_exception_type((CoinApiRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=120),
        reraise=True,
    )
    def fetch(url: str) -> Any:
        return _fetch(session, url, headers, logger)

    if config.kind == "reference":
        data = fetch(_build_url(config.path, {}))
        if isinstance(data, list) and data:
            yield data
        return

    if config.kind == "exchange_rate":
        base = exchange_rate_base_asset or "USD"
        data = fetch(_build_url(config.path.replace("{base}", base), {}))
        rates = data.get("rates", []) if isinstance(data, dict) else []
        base_asset = data.get("asset_id_base", base) if isinstance(data, dict) else base
        rows = [{**rate, "asset_id_base": base_asset} for rate in rates]
        if rows:
            yield rows
        return

    # Time-series endpoint.
    if not symbol_id:
        raise ValueError(
            f"CoinAPI endpoint '{endpoint}' requires a symbol_id. Set the Symbol ID field on the source "
            f"(e.g. BITSTAMP_SPOT_BTC_USD) to sync this table."
        )

    cursor = incremental_field or config.incremental_fields[0]["field"]
    initial_time_start = _initial_time_start(should_use_incremental_field, db_incremental_field_last_value, start_date)

    yield from _get_timeseries_rows(
        config=config,
        logger=logger,
        fetch=fetch,
        symbol_id=symbol_id,
        period_id=period_id or "1DAY",
        incremental_field=cursor,
        initial_time_start=initial_time_start,
        resumable_source_manager=resumable_source_manager,
    )


def coin_api_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CoinApiResumeConfig],
    symbol_id: str = "",
    period_id: str = "1DAY",
    exchange_rate_base_asset: str = "USD",
    start_date: str = "",
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = COIN_API_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            symbol_id=symbol_id,
            period_id=period_id,
            exchange_rate_base_asset=exchange_rate_base_asset,
            start_date=start_date,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
