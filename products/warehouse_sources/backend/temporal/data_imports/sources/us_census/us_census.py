import re
import json
from collections.abc import Iterator, Sequence
from typing import Any, Optional
from urllib.parse import urlencode

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.us_census.settings import (
    CENSUS_API_BASE_URL,
    MAX_VARIABLES_PER_QUERY,
    VALIDATION_DATASET,
    VALIDATION_GEOGRAPHY,
)

_REQUEST_TIMEOUT = 120

# Rows per yielded chunk. The full response is already in memory (the API has no
# pagination), so this only bounds the size of each batch handed to the pipeline.
_ROWS_PER_CHUNK = 5000

# The API signals a missing/invalid key with a 302 to an HTML error page and this header.
_KEY_ERROR_HEADER = "X-DataWebAPI-KeyError"

AUTH_ERROR_MESSAGE = "US Census API key is missing or invalid"
REQUEST_ERROR_PREFIX = "US Census API rejected the request"
RESPONSE_SHAPE_ERROR_PREFIX = "Unexpected response from the US Census API"
RESPONSE_TOO_LARGE_PREFIX = "US Census API response is too large"

# Cap on the decoded response body. The API has no pagination, so a high-cardinality
# custom query (e.g. every census block nationwide) would otherwise buffer an unbounded
# body plus parsed copies in memory.
_MAX_RESPONSE_BYTES = 256 * 1024 * 1024
_STREAM_CHUNK_BYTES = 1024 * 1024

_DATASET_PATH_REGEX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/_.-]*$")


def build_query_url(
    dataset: str,
    variables: Sequence[str],
    geography: str,
    geography_filter: Optional[str] = None,
    predicates: Sequence[tuple[str, str]] = (),
    api_key: str = "",
) -> str:
    params: list[tuple[str, str]] = [("get", ",".join(variables)), ("for", geography)]
    if geography_filter:
        params.append(("in", geography_filter))
    params.extend(predicates)
    if api_key:
        params.append(("key", api_key))
    # Keep `:`, `*`, and `,` literal — the documented Census query syntax uses them raw
    # (e.g. for=state:*), and percent-encoding them is unverified against this API.
    return f"{CENSUS_API_BASE_URL}/{dataset.strip('/')}?{urlencode(params, safe=':*,')}"


def _is_key_error(response: Response) -> bool:
    return response.status_code in (301, 302, 303, 307, 308) and (
        response.headers.get(_KEY_ERROR_HEADER) is not None or "key" in response.headers.get("Location", "").lower()
    )


def _raise_for_error(response: Response) -> None:
    if _is_key_error(response):
        raise ValueError(f"{AUTH_ERROR_MESSAGE}. Request a free key at https://api.census.gov/data/key_signup.html")
    if not response.ok:
        # 4xx bodies carry the reason as plain text (e.g. "error: unknown variable 'X'").
        raise ValueError(f"{REQUEST_ERROR_PREFIX} ({response.status_code}): {response.text[:500]}")


def rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    """Zip the Census 2D array-of-arrays payload (first row = column headers) into row dicts."""
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], list):
        raise ValueError(f"{RESPONSE_SHAPE_ERROR_PREFIX}: expected a JSON array of arrays")
    header = [str(column) for column in payload[0]]
    return [dict(zip(header, row)) for row in payload[1:]]


def parse_custom_variables(raw: str) -> tuple[str, ...]:
    return tuple(variable.strip() for variable in raw.split(",") if variable.strip())


def validate_custom_query(
    dataset: Optional[str],
    variables: Optional[str],
    geography: Optional[str],
) -> str | None:
    """Validate the custom query config fields; returns a user-facing error message or None."""
    values = (dataset or "", variables or "", geography or "")
    if not any(value.strip() for value in values):
        return None
    if not all(value.strip() for value in values):
        return "US Census custom query is incomplete: set the dataset path, variables, and geography together"
    assert dataset is not None and variables is not None and geography is not None
    if not _DATASET_PATH_REGEX.match(dataset.strip().strip("/")):
        return "US Census custom query dataset path is invalid: use a vintage/dataset path like 2024/acs/acs5"
    parsed_variables = parse_custom_variables(variables)
    if not parsed_variables:
        return "US Census custom query variables are invalid: provide a comma-separated list like NAME,B01001_001E"
    if len(parsed_variables) > MAX_VARIABLES_PER_QUERY:
        return f"US Census custom query requests too many variables: the API allows at most {MAX_VARIABLES_PER_QUERY} per query"
    return None


def get_rows(
    api_key: str,
    dataset: str,
    variables: Sequence[str],
    geography: str,
    geography_filter: Optional[str],
    predicates: Sequence[tuple[str, str]],
) -> Iterator[list[dict[str, Any]]]:
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
    url = build_query_url(dataset, variables, geography, geography_filter, predicates, api_key)
    # Stream so an oversized body is rejected at the byte cap instead of buffered whole;
    # the request timeout applies per read between chunks, bounding the transfer.
    response = session.get(url, timeout=_REQUEST_TIMEOUT, stream=True)
    _raise_for_error(response)

    body = bytearray()
    for chunk in response.iter_content(chunk_size=_STREAM_CHUNK_BYTES):
        body.extend(chunk)
        if len(body) > _MAX_RESPONSE_BYTES:
            response.close()
            raise ValueError(
                f"{RESPONSE_TOO_LARGE_PREFIX} (over {_MAX_RESPONSE_BYTES // (1024 * 1024)} MiB). "
                "Narrow the query with fewer variables or a smaller geography (e.g. an in= filter)."
            )

    try:
        payload = json.loads(bytes(body))
    except ValueError as e:
        raise ValueError(f"{RESPONSE_SHAPE_ERROR_PREFIX}: body is not valid JSON") from e

    rows = rows_from_payload(payload)
    for start in range(0, len(rows), _ROWS_PER_CHUNK):
        yield rows[start : start + _ROWS_PER_CHUNK]


def us_census_source(
    api_key: str,
    endpoint: str,
    dataset: str,
    variables: Sequence[str],
    geography: str,
    geography_filter: Optional[str] = None,
    predicates: Sequence[tuple[str, str]] = (),
    primary_keys: Optional[list[str]] = None,
) -> SourceResponse:
    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            dataset=dataset,
            variables=variables,
            geography=geography,
            geography_filter=geography_filter,
            predicates=predicates,
        ),
        primary_keys=primary_keys,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    if not api_key or not api_key.strip():
        return False, "US Census API key is required. Request a free key at https://api.census.gov/data/key_signup.html"

    url = build_query_url(VALIDATION_DATASET, ("NAME",), VALIDATION_GEOGRAPHY, api_key=api_key)
    try:
        response = make_tracked_session(redact_values=(api_key,), allow_redirects=False).get(url, timeout=30)
    except Exception:
        return False, "Could not reach the US Census API. Please try again later."

    if response.status_code == 200:
        return True, None
    if _is_key_error(response):
        return (
            False,
            "US Census API key was rejected. Request a free key at https://api.census.gov/data/key_signup.html",
        )
    return False, f"US Census API returned an unexpected status ({response.status_code}). Please try again later."
