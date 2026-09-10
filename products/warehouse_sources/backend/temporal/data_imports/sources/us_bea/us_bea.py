import re
import json
from collections.abc import Iterator, Mapping
from typing import Any, Optional
from urllib.parse import urlencode

from requests import Response, Session

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.us_bea.settings import (
    BEA_API_BASE_URL,
    VALIDATION_DATASET_NAME,
    BeaEndpointConfig,
)

_REQUEST_TIMEOUT = 120

# Rows per yielded chunk. GetData responses aren't paginated (BEA returns the whole
# requested slice in one call), so this only bounds the size of each batch handed to the
# pipeline's batcher.
_ROWS_PER_CHUNK = 5000

# GetData isn't paginated, so a broad custom query (e.g. GeoFips=STATE with Year=ALL across a
# large dataset) can return a very large single body. requests buffers the whole response into
# memory by default and json.loads then duplicates it while parsing, so stream the body and cap
# what's read into memory instead of trusting the request to stay small. Generous enough for any
# documented BEA regional/national table.
_MAX_RESPONSE_BYTES = 128 * 1024 * 1024
_RESPONSE_CHUNK_BYTES = 256 * 1024

AUTH_ERROR_MESSAGE = "BEA UserID is missing or invalid"
REQUEST_ERROR_PREFIX = "BEA API rejected the request"
RESPONSE_SHAPE_ERROR_PREFIX = "Unexpected response from the BEA API"
RESPONSE_TOO_LARGE_ERROR = "BEA API response body was too large"

# BEA dataset names are a single alphanumeric token (NIPA, Regional, ITA, GDPbyIndustry, ...).
_DATASET_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")


class UsBeaApiError(Exception):
    pass


class UsBeaAuthenticationError(UsBeaApiError):
    pass


class UsBeaRequestError(UsBeaApiError):
    """A rejected request that retrying cannot fix - an unknown table, geography, or year."""


class UsBeaResponseTooLargeError(UsBeaApiError):
    """Non-retryable: re-issuing the same query returns the same oversized body."""


def build_query_url(
    user_id: str, method: str, dataset_name: Optional[str] = None, params: Optional[Mapping[str, str]] = None
) -> str:
    query: dict[str, str] = {"UserID": user_id, "method": method, "ResultFormat": "JSON"}
    if dataset_name is not None:
        query["datasetname"] = dataset_name
    if params:
        query.update(params)
    return f"{BEA_API_BASE_URL}?{urlencode(query)}"


def parse_custom_query_params(raw: str) -> dict[str, str]:
    """Parse the source's freeform "Key=Value,Key=Value" custom query params field."""
    params: dict[str, str] = {}
    for pair in raw.split(","):
        cleaned = pair.strip()
        if "=" not in cleaned:
            continue
        key, _, value = cleaned.partition("=")
        key = key.strip()
        if key:
            params[key] = value.strip()
    return params


def validate_custom_query(dataset_name: Optional[str], params_raw: Optional[str]) -> str | None:
    """Validate the custom query config fields; returns a user-facing error message or None."""
    values = (dataset_name or "", params_raw or "")
    if not any(value.strip() for value in values):
        return None
    if not all(value.strip() for value in values):
        return "BEA custom query is incomplete: set both the dataset name and the query parameters"
    assert dataset_name is not None and params_raw is not None
    if not _DATASET_NAME_RE.match(dataset_name.strip()):
        return "BEA custom query dataset name is invalid. Use a BEA DatasetName like NIPA, Regional, or ITA."
    if not parse_custom_query_params(params_raw):
        return (
            "BEA custom query parameters are invalid. Use a comma-separated list like "
            "TableName=T10101,Frequency=Q,Year=ALL"
        )
    return None


def _results_list(payload: Any) -> list[dict[str, Any]]:
    """BEA nests results under BEAAPI.Results, a dict normally but a list when a request
    spans multiple result sets (e.g. a dataset that accepts multiple TableNames)."""
    try:
        results = payload["BEAAPI"]["Results"]
    except (KeyError, TypeError):
        return []
    if isinstance(results, list):
        return [result for result in results if isinstance(result, dict)]
    if isinstance(results, dict):
        return [results]
    return []


def _extract_error(payload: Any) -> Optional[str]:
    for result in _results_list(payload):
        error = result.get("Error")
        if isinstance(error, list):
            error = error[0] if error else None
        if isinstance(error, dict):
            return str(error.get("APIErrorDescription") or "BEA API error")
    return None


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in _results_list(payload):
        data = result.get("Data")
        if data is None:
            continue
        data_list = data if isinstance(data, list) else [data]
        rows.extend(row for row in data_list if isinstance(row, dict))
    return rows


def _raise_for_error(response: Response, payload: Any) -> None:
    # BEA reports invalid credentials and bad parameters as HTTP 200 with an Error node in
    # the body, not via the HTTP status - only throttling (429) is a real status-code error.
    description = _extract_error(payload)
    if description is not None:
        if "userid" in description.lower():
            raise UsBeaAuthenticationError(f"{AUTH_ERROR_MESSAGE}: {description}")
        raise UsBeaRequestError(f"{REQUEST_ERROR_PREFIX}: {description}")
    if not response.ok:
        raise UsBeaApiError(f"BEA API error: status={response.status_code}")


def _read_capped_body(response: Response, max_bytes: Optional[int] = None) -> bytes:
    """Read a streamed response body into memory, aborting past `max_bytes`.

    Called on a response opened with `stream=True` so nothing is buffered until here.

    `max_bytes` defaults to the module-level `_MAX_RESPONSE_BYTES`, looked up at call time
    (not bound as a default argument value) so tests can patch it.
    """
    if max_bytes is None:
        max_bytes = _MAX_RESPONSE_BYTES
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=_RESPONSE_CHUNK_BYTES):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise UsBeaResponseTooLargeError(f"{RESPONSE_TOO_LARGE_ERROR}: exceeded {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def _fetch(session: Session, url: str) -> dict[str, Any]:
    response = session.get(url, timeout=_REQUEST_TIMEOUT, stream=True)
    try:
        body = _read_capped_body(response)
        try:
            payload = json.loads(body)
        except ValueError as e:
            if not response.ok:
                raise UsBeaApiError(f"BEA API error: status={response.status_code}") from e
            raise ValueError(f"{RESPONSE_SHAPE_ERROR_PREFIX}: body is not valid JSON") from e
    finally:
        response.close()
    _raise_for_error(response, payload)
    if not isinstance(payload, dict):
        raise ValueError(f"{RESPONSE_SHAPE_ERROR_PREFIX}: expected a JSON object")
    return payload


def get_data_rows(session: Session, user_id: str, dataset_name: str, params: Mapping[str, str]) -> list[dict[str, Any]]:
    url = build_query_url(user_id, "GetData", dataset_name, params)
    return _extract_rows(_fetch(session, url))


def get_endpoint_rows(user_id: str, endpoint: BeaEndpointConfig) -> Iterator[list[dict[str, Any]]]:
    """One GetData call per documented LineCode, merged into a single stream.

    Each row already carries a `Code` field like "SAINC1-3" that embeds the table and line
    code, so rows from different LineCode calls never collide on primary key.
    """
    session = make_tracked_session(redact_values=(user_id,))
    for line_code in endpoint.line_codes:
        params = {"TableName": endpoint.table_name, "LineCode": line_code, **endpoint.extra_params}
        rows = get_data_rows(session, user_id, endpoint.dataset_name, params)
        for start in range(0, len(rows), _ROWS_PER_CHUNK):
            yield rows[start : start + _ROWS_PER_CHUNK]


def get_custom_query_rows(user_id: str, dataset_name: str, params: Mapping[str, str]) -> Iterator[list[dict[str, Any]]]:
    session = make_tracked_session(redact_values=(user_id,))
    rows = get_data_rows(session, user_id, dataset_name, params)
    for start in range(0, len(rows), _ROWS_PER_CHUNK):
        yield rows[start : start + _ROWS_PER_CHUNK]


def us_bea_source(
    user_id: str,
    endpoint: str,
    endpoint_config: Optional[BeaEndpointConfig],
    custom_dataset_name: Optional[str] = None,
    custom_params: Optional[Mapping[str, str]] = None,
) -> SourceResponse:
    if endpoint_config is not None:
        return SourceResponse(
            name=endpoint,
            items=lambda: get_endpoint_rows(user_id, endpoint_config),
            primary_keys=list(endpoint_config.primary_keys),
        )

    assert custom_dataset_name is not None and custom_params is not None
    return SourceResponse(
        name=endpoint,
        # The geography/dimension columns of an arbitrary custom query aren't known ahead of
        # time, so no primary keys are declared and the table stays full refresh.
        items=lambda: get_custom_query_rows(user_id, custom_dataset_name, custom_params),
        primary_keys=None,
    )


def validate_credentials(user_id: str) -> tuple[bool, str | None]:
    if not user_id or not user_id.strip():
        return False, f"{AUTH_ERROR_MESSAGE}. Register a free UserID at https://apps.bea.gov/api/signup/"

    session = make_tracked_session(redact_values=(user_id,))
    url = build_query_url(user_id, "GetParameterList", VALIDATION_DATASET_NAME)
    try:
        response = session.get(url, timeout=30)
        payload = response.json()
    except Exception:
        return False, "Could not reach the BEA API. Please try again later."

    try:
        _raise_for_error(response, payload)
    except UsBeaAuthenticationError:
        return False, f"{AUTH_ERROR_MESSAGE}. Register a free UserID at https://apps.bea.gov/api/signup/"
    except UsBeaApiError:
        return False, "BEA API returned an unexpected response. Please try again later."

    return True, None
