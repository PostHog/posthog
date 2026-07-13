"""Client for the backend data plane — the sandbox's only read path to PostHog data.

POSTs a HogQL query to the backend's data-plane endpoint (authed with the
run-scoped data-plane token), which enqueues it on the backend's async query
manager and returns a query_id; this client then polls the status endpoint until
the rows come back as an Arrow stream. No backend web worker waits on ClickHouse
— and this thread is the kernel's own, invisible to the user. Uses urllib so the
only third-party dependency is pyarrow (present in the sandbox image).
"""

import json
import time
import urllib.error
import urllib.request
from typing import Any

import pyarrow as pa

_REQUEST_TIMEOUT_SECONDS = 30
# Total budget for one query: enqueue + Celery pickup + ClickHouse execution.
_POLL_DEADLINE_SECONDS = 180
_POLL_INITIAL_INTERVAL_SECONDS = 0.3
_POLL_MAX_INTERVAL_SECONDS = 2.0


class DataPlaneError(Exception):
    """A query the data plane rejected or failed to run; message is user-facing."""


def fetch_query_page(
    url: str, token: str, query: str, limit: int, offset: int = 0
) -> tuple[list[str], list[tuple[Any, ...]], list[list[str]]]:
    """Run `query` through the data plane; return (columns, rows, types) of the capped page."""
    request = urllib.request.Request(
        url,
        data=json.dumps({"query": query, "limit": limit, "offset": offset}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        # url is the backend's own data-plane endpoint from the signed run payload, never user-controlled.
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            if _is_arrow(response):
                # A pre-async-manager backend answers the POST with the rows directly.
                return decode_arrow_stream(response)
            body = json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise DataPlaneError(_error_detail(exc)) from exc
    except urllib.error.URLError as exc:
        raise DataPlaneError(f"Could not reach the data plane: {exc.reason}") from exc
    except pa.ArrowInvalid as exc:
        raise DataPlaneError(f"Invalid Arrow response from the data plane: {exc}") from exc

    query_id = body.get("query_id")
    if not query_id:
        raise DataPlaneError("Data plane did not accept the query")
    return _poll_for_result(f"{url.rstrip('/')}/{query_id}/", token)


def _poll_for_result(status_url: str, token: str) -> tuple[list[str], list[tuple[Any, ...]], list[list[str]]]:
    request = urllib.request.Request(status_url, headers={"Authorization": f"Bearer {token}"}, method="GET")
    deadline = time.monotonic() + _POLL_DEADLINE_SECONDS
    interval = _POLL_INITIAL_INTERVAL_SECONDS
    while time.monotonic() < deadline:
        try:
            # status_url is the backend's own data-plane endpoint from the signed run payload, not user input.
            # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
                if _is_arrow(response):
                    return decode_arrow_stream(response)
                # 202 — still running.
        except urllib.error.HTTPError as exc:
            raise DataPlaneError(_error_detail(exc)) from exc
        except urllib.error.URLError as exc:
            raise DataPlaneError(f"Could not reach the data plane: {exc.reason}") from exc
        except pa.ArrowInvalid as exc:
            raise DataPlaneError(f"Invalid Arrow response from the data plane: {exc}") from exc
        time.sleep(interval)
        interval = min(interval * 1.5, _POLL_MAX_INTERVAL_SECONDS)
    raise DataPlaneError("Timed out waiting for the query to finish")


def _is_arrow(response: Any) -> bool:
    return "arrow" in (response.headers.get("Content-Type") or "")


def decode_arrow_stream(source: Any) -> tuple[list[str], list[tuple[Any, ...]], list[list[str]]]:
    """Decode an Arrow IPC stream (file-like or bytes-like) into (columns, rows, types).

    Types come from the `hogql_types` schema metadata the data plane attaches (the
    real ClickHouse type names); when absent they are approximated from the Arrow
    schema so the envelope always carries something usable for axis detection.
    """
    table = pa.ipc.open_stream(source).read_all()
    columns = table.column_names
    # Columnar → row tuples without to_pylist(), which would collapse duplicate column names.
    column_values = [table.column(i).to_pylist() for i in range(table.num_columns)]
    rows = list(zip(*column_values)) if column_values else []

    metadata = table.schema.metadata or {}
    raw_types = metadata.get(b"hogql_types")
    if raw_types:
        try:
            types = [[str(name), str(type_name)] for name, type_name in json.loads(raw_types)]
        except (json.JSONDecodeError, ValueError, TypeError):
            types = _types_from_arrow_schema(table.schema)
    else:
        types = _types_from_arrow_schema(table.schema)
    return columns, rows, types


def _types_from_arrow_schema(schema: Any) -> list[list[str]]:
    def type_name(arrow_type: Any) -> str:
        if pa.types.is_boolean(arrow_type):
            return "Bool"
        if pa.types.is_integer(arrow_type):
            return "Int64"
        if pa.types.is_floating(arrow_type) or pa.types.is_decimal(arrow_type):
            return "Float64"
        if pa.types.is_timestamp(arrow_type):
            return "DateTime"
        if pa.types.is_date(arrow_type):
            return "Date"
        return "String"

    return [[field.name, type_name(field.type)] for field in schema]


def _error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(exc.read().decode("utf-8", "replace"))
        detail = body.get("error")
        if isinstance(detail, str) and detail:
            return detail
    except (json.JSONDecodeError, ValueError, OSError):
        pass
    return f"Data plane request failed with HTTP {exc.code}"
