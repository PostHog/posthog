import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.financial_modelling.settings import (
    FINANCIAL_MODELLING_BASE_URL,
    FINANCIAL_MODELLING_ENDPOINTS,
    FinancialModellingEndpointConfig,
)

# Free-tier keys are heavily rate-limited (~250 req/day) and return HTTP 429 once exceeded, so we
# back off on 429 and transient 5xx and otherwise let `raise_for_status` surface the error.
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5


class FinancialModellingRetryableError(Exception):
    pass


class FinancialModellingError(Exception):
    """FMP returned a JSON error body (e.g. plan restriction) rather than a result array."""


@dataclasses.dataclass
class FinancialModellingResumeConfig:
    # Index into the configured symbol list of the next symbol to fetch. For market-wide endpoints
    # (no fan-out) this stays 0. The symbol list is user-defined and stable across runs, so a stored
    # index resumes into the same symbol.
    symbol_index: int = 0


def parse_symbols(raw: str | None) -> list[str]:
    """Split a user-entered symbol list (comma/whitespace separated) into normalized tickers."""
    if not raw:
        return []
    tokens = raw.replace("\n", ",").replace(" ", ",").split(",")
    seen: set[str] = set()
    symbols: list[str] = []
    for token in tokens:
        symbol = token.strip().upper()
        if symbol and symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)
    return symbols


def _build_url(path: str, params: dict[str, Any], api_key: str) -> str:
    query = urlencode({**params, "apikey": api_key})
    return f"{FINANCIAL_MODELLING_BASE_URL}/{path}?{query}"


@retry(
    retry=retry_if_exception_type((FinancialModellingRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    params: dict[str, Any],
    api_key: str,
    logger: FilteringBoundLogger,
) -> Any:
    url = _build_url(path, params, api_key)
    response = session.get(url, headers={"Accept": "application/json"}, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise FinancialModellingRetryableError(
            f"Financial Modeling Prep API error (retryable): status={response.status_code}, path={path}"
        )

    if not response.ok:
        logger.error(f"Financial Modeling Prep API error: status={response.status_code}, path={path}")
        # `raise_for_status` would embed the full request URL — which carries the apikey — in the
        # exception text, leaking the credential into stored error state. Re-raise with a sanitized
        # URL that preserves the stable "<status> Client Error: <reason> for url: <base>/<path>" text
        # get_non_retryable_errors matches on (this path only handles 4xx; 429/5xx are handled above).
        raise requests.HTTPError(
            f"{response.status_code} Client Error: {response.reason} for url: {FINANCIAL_MODELLING_BASE_URL}/{path}",
            response=response,
        )

    return response.json()


def _extract_rows(data: Any, response_key: str | None) -> list[dict[str, Any]]:
    """Normalize an FMP response into a list of row dicts.

    Stable endpoints return a bare JSON array. Some historical-data endpoints instead wrap the array
    under a key (e.g. {"symbol": ..., "historical": [...]}). Error responses are JSON objects carrying
    an "Error Message" field.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "Error Message" in data:
            # FMP returns HTTP 200 with this body for plan restrictions and invalid keys, which a
            # retry can't fix. The stable prefix lets get_non_retryable_errors match it so the schema
            # is disabled with a friendly message instead of looping on every scheduled run.
            raise FinancialModellingError(
                f"Financial Modeling Prep API returned an error response: {data['Error Message']}"
            )
        if response_key and isinstance(data.get(response_key), list):
            return data[response_key]
        return [data]
    return []


def validate_credentials(api_key: str) -> bool:
    # `profile` is a cheap, free-tier endpoint; a genuine key returns 200, a bad one returns 401.
    url = _build_url("profile", {"symbol": "AAPL"}, api_key)
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            url, headers={"Accept": "application/json"}, timeout=10
        )
        return response.status_code == 200
    except Exception:
        return False


def _to_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def _window_params(
    config: FinancialModellingEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, str]:
    """Build the `from`/`to` server-side date filter for incremental endpoints."""
    if not config.supports_date_window:
        return {}

    today = datetime.now(UTC).date()
    from_date: date | None = None

    if should_use_incremental_field and db_incremental_field_last_value:
        from_date = _to_date(db_incremental_field_last_value)
        # A future-dated cursor (bad source data) would otherwise build an empty/invalid window.
        if from_date and from_date > today:
            from_date = today
    elif config.default_lookback_days:
        from_date = today - timedelta(days=config.default_lookback_days)

    if from_date is None:
        return {}
    return {"from": from_date.isoformat(), "to": today.isoformat()}


def get_rows(
    api_key: str,
    endpoint: str,
    symbols: list[str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FinancialModellingResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = FINANCIAL_MODELLING_ENDPOINTS[endpoint]
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    session = make_tracked_session(redact_values=(api_key,))
    window = _window_params(config, should_use_incremental_field, db_incremental_field_last_value)

    if config.fan_out_over_symbols:
        resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
        start_index = resume.symbol_index if resume is not None else 0
        if start_index:
            logger.debug(f"Financial Modeling Prep: resuming {endpoint} from symbol index {start_index}")

        for offset, symbol in enumerate(symbols[start_index:]):
            index = start_index + offset
            params: dict[str, Any] = {"symbol": symbol, **config.extra_params, **window}
            data = _fetch_page(session, config.path, params, api_key, logger)
            for row in _extract_rows(data, config.response_key):
                row.setdefault("symbol", symbol)
                batcher.batch(row)
                if batcher.should_yield():
                    yield batcher.get_table()

            # Flush this symbol's rows before advancing the bookmark, so a crash re-fetches only from
            # the next symbol (whose rows are not yet persisted) rather than dropping buffered rows.
            if batcher.should_yield(include_incomplete_chunk=True):
                yield batcher.get_table()
            if index + 1 < len(symbols):
                resumable_source_manager.save_state(FinancialModellingResumeConfig(symbol_index=index + 1))
        return

    params = {**config.extra_params, **window}
    data = _fetch_page(session, config.path, params, api_key, logger)
    for row in _extract_rows(data, config.response_key):
        batcher.batch(row)
        if batcher.should_yield():
            yield batcher.get_table()

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def financial_modelling_source(
    api_key: str,
    endpoint: str,
    symbols: list[str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FinancialModellingResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = FINANCIAL_MODELLING_ENDPOINTS[endpoint]
    is_incremental = bool(config.incremental_fields)

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            symbols=symbols,
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
        # Rows arrive grouped per symbol (fan-out) and/or newest-first, never globally cursor-ascending,
        # so use "desc": the pipeline commits the high watermark as the global max at run end instead of
        # checkpointing per batch (which could skip a later symbol's older rows after an interruption).
        sort_mode="desc" if is_incremental else "asc",
    )
