from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.rki_covid.settings import (
    RKI_COVID_ENDPOINTS,
    RKICovidEndpointConfig,
)

RKI_COVID_BASE_URL = "https://api.corona-zahlen.org"

# Every dataset is bounded (the pandemic time series is a few thousand rows, districts ~400 rows),
# so no history window cap is needed beyond the optional user-configured `history_days`.


class RKICovidAPIError(Exception):
    pass


def build_url(config: RKICovidEndpointConfig, history_days: Optional[int]) -> str:
    # History endpoints accept an optional `/:days` suffix that trims the returned window
    # server-side (relative to today — not an absolute cursor, so tables stay full refresh).
    if config.supports_days and history_days:
        return f"{RKI_COVID_BASE_URL}{config.path}/{history_days}"
    return f"{RKI_COVID_BASE_URL}{config.path}"


def _fetch(session: requests.Session, url: str) -> dict[str, Any]:
    # make_tracked_session already retries 429/5xx honoring Retry-After; no extra retry layer here.
    response = session.get(url, timeout=60)
    response.raise_for_status()

    body = response.json()
    if not isinstance(body, dict):
        raise RKICovidAPIError("RKI COVID-19 API error [unexpected_response]: response was not a JSON object")

    # The API signals some failures with HTTP 200 and an `error` envelope in the body.
    if "error" in body:
        raise RKICovidAPIError(f"RKI COVID-19 API error [error_response]: {body['error']}")

    return body


def _parse_snapshot(body: dict[str, Any], config: RKICovidEndpointConfig) -> Iterator[dict[str, Any]]:
    yield body


def _parse_dict_rows(body: dict[str, Any], config: RKICovidEndpointConfig) -> Iterator[dict[str, Any]]:
    data = body.get("data")
    if not isinstance(data, dict):
        return
    for value in data.values():
        if isinstance(value, dict):
            yield value


def _parse_keyed_rows(body: dict[str, Any], config: RKICovidEndpointConfig) -> Iterator[dict[str, Any]]:
    data = body.get("data")
    if not isinstance(data, dict):
        return
    for key, value in data.items():
        if isinstance(value, dict):
            # The dict key (e.g. the age-group band) carries the row identity and is the primary key.
            assert config.key_field is not None
            yield {config.key_field: key, **value}


def _parse_data_list(body: dict[str, Any], config: RKICovidEndpointConfig) -> Iterator[dict[str, Any]]:
    data = body.get("data")
    if not isinstance(data, list):
        return
    for row in data:
        if isinstance(row, dict):
            yield row


def _parse_data_history(body: dict[str, Any], config: RKICovidEndpointConfig) -> Iterator[dict[str, Any]]:
    data = body.get("data")
    if not isinstance(data, dict):
        return
    history = data.get("history")
    if not isinstance(history, list):
        return
    for row in history:
        if isinstance(row, dict):
            yield row


_PARSERS = {
    "snapshot": _parse_snapshot,
    "dict_rows": _parse_dict_rows,
    "keyed_rows": _parse_keyed_rows,
    "data_list": _parse_data_list,
    "data_history": _parse_data_history,
}


def get_rows(
    endpoint: str,
    history_days: Optional[int],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = RKI_COVID_ENDPOINTS[endpoint]
    parser = _PARSERS[config.kind]
    session = make_tracked_session()

    body = _fetch(session, build_url(config, history_days))
    rows = list(parser(body, config))
    logger.debug(f"RKI COVID-19: fetched {len(rows)} rows for {endpoint}")
    if rows:
        yield rows


def rki_covid_source(
    endpoint: str,
    history_days: Optional[int],
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = RKI_COVID_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(endpoint=endpoint, history_days=history_days, logger=logger),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_connection() -> bool:
    """Confirm the public API is reachable by issuing one cheap probe request.

    The API is unauthenticated, so this only verifies availability of the community-run service.
    """
    try:
        session = make_tracked_session()
        response = session.get(f"{RKI_COVID_BASE_URL}/germany", timeout=10)
    except Exception:
        return False

    if response.status_code != 200:
        return False

    try:
        body = response.json()
    except ValueError:
        return False

    return isinstance(body, dict) and "error" not in body
