"""Client for the backend data plane — the sandbox's only read path to PostHog data.

POSTs a HogQL query to the backend's data-plane endpoint (authed with the
run-scoped data-plane token), which enqueues it on the backend's async query
manager and returns a query_id; this client then polls the status endpoint until
the rows come back as an Arrow stream. No backend web worker waits on ClickHouse
— and this thread is the kernel's own, invisible to the user. Uses urllib so the
only third-party dependency is pyarrow (present in the sandbox image).
"""

import os
import json
import time
import threading
import urllib.error
import urllib.request
from typing import Any

import pyarrow as pa

_REQUEST_TIMEOUT_SECONDS = 30
# Total budget for one inline query: enqueue + Celery pickup + ClickHouse execution.
_POLL_DEADLINE_SECONDS = 180
# Object materialization is dispatched to a Temporal workflow whose schedule_to_close is
# 10 minutes over a 500k-row / 50GB-scan ceiling — exactly the large frames this path
# exists to carry. The client budget must cover the server budget (plus margin for the
# final poll interval), or the headline case times out client-side while the worker keeps
# producing an object nobody fetches. Sync with NotebookFrameMaterializeWorkflow's
# schedule_to_close_timeout in temporal/frame_materialize.py.
_OBJECT_POLL_DEADLINE_SECONDS = 660
_POLL_INITIAL_INTERVAL_SECONDS = 0.3
_POLL_MAX_INTERVAL_SECONDS = 2.0


class DataPlaneError(Exception):
    """A query the data plane rejected or failed to run; message is user-facing."""


class DataPlaneInterrupted(DataPlaneError):
    """The run's cancel event fired while waiting on the data plane."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Surface 3xx responses as HTTPError instead of auto-following.

    urllib re-sends all request headers on a redirect — including Authorization — which
    would ship the data-plane bearer token to the object-store host (and S3 rejects
    requests carrying both header auth and presigned query auth). The poll intercepts the
    302 and fetches the presigned URL with a clean, credential-free request instead.
    """

    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> urllib.request.Request | None:
        return None


_no_redirect_opener = urllib.request.build_opener(_NoRedirectHandler)


# How much of a presigned frame URL may be surfaced for observability. The URL is a
# bearer secret; the first 30 characters cover scheme + host (which store served the
# frame) and never reach the signature query parameters.
_FRAME_SOURCE_PREVIEW_CHARS = 30


def fetch_query_page(
    url: str,
    token: str,
    query: str,
    limit: int,
    offset: int = 0,
    cancel_event: "threading.Event | None" = None,
) -> tuple[list[str], list[tuple[Any, ...]], list[list[str]]]:
    """Run `query` through the data plane; return (columns, rows, types) of the capped page."""
    table, _source = _request_table(url, token, query, limit, offset, cancel_event=cancel_event)
    return _table_to_rows_and_types(table)


def materialize_query_to_file(
    url: str,
    token: str,
    query: str,
    dest_path: str,
    limit: int,
    offset: int = 0,
    cancel_event: "threading.Event | None" = None,
) -> tuple[int, str | None]:
    """Fetch the full result of `query` and write it as a local Arrow IPC file for a Python/DuckDB node.

    Returns (row count, truncated frame-store URL preview) — the preview is set only when
    the frame actually came from a presigned object download (None on the inline fallback),
    so callers can surface which store served the frame. Requests object delivery: the poll
    answers with a 302 to a presigned object-store URL carrying the same Arrow bytes
    (falling back to the inline body when the backend's frame store is unavailable). The
    file is written to a temp name and renamed on success so a torn write (e.g. a
    mid-stream failure) never leaves a half-frame the kernel could read.
    """
    table, source = _request_table(url, token, query, limit, offset, delivery="object", cancel_event=cancel_event)
    temp_path = f"{dest_path}.partial"
    with pa.OSFile(temp_path, "wb") as sink:
        with pa.ipc.new_file(sink, table.schema) as writer:
            writer.write_table(table)
    os.replace(temp_path, dest_path)
    return table.num_rows, source


def _check_cancelled(cancel_event: "threading.Event | None") -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise DataPlaneInterrupted("Run interrupted.")


def _request_table(
    url: str,
    token: str,
    query: str,
    limit: int,
    offset: int,
    delivery: str = "inline",
    cancel_event: "threading.Event | None" = None,
) -> tuple["pa.Table", str | None]:
    """POST the query and (once the async manager finishes) return the raw Arrow table.

    The second element is a truncated presigned-URL preview when the rows came from an
    object download, else None.
    """
    _check_cancelled(cancel_event)
    body: dict[str, Any] = {"query": query, "limit": limit, "offset": offset}
    if delivery != "inline":
        # Only sent when non-default, keeping page requests byte-identical for old backends.
        body["delivery"] = delivery
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        # url is the backend's own data-plane endpoint from the signed run payload, never user-controlled.
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            if _is_arrow(response):
                # A pre-async-manager backend answers the POST with the rows directly.
                return _read_table(response), None
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
    return _poll_for_table(
        f"{url.rstrip('/')}/{query_id}/", token, expect_object=delivery == "object", cancel_event=cancel_event
    )


def _poll_for_table(
    status_url: str,
    token: str,
    expect_object: bool = False,
    cancel_event: "threading.Event | None" = None,
) -> tuple["pa.Table", str | None]:
    request = urllib.request.Request(status_url, headers={"Authorization": f"Bearer {token}"}, method="GET")
    # Only object-delivery polls intercept the completion 302 (a presigned frame handoff).
    # Inline polls keep urllib's transparent redirect-following, so an infrastructure
    # redirect (HTTPS upgrade, trailing-slash canonicalization) on a page fetch behaves as
    # it did before object delivery existed — no auth-header leak concern, since the target
    # is still our own data plane and inline responses carry no presigned URL.
    opener = _no_redirect_opener.open if expect_object else urllib.request.urlopen
    deadline = time.monotonic() + (_OBJECT_POLL_DEADLINE_SECONDS if expect_object else _POLL_DEADLINE_SECONDS)
    interval = _POLL_INITIAL_INTERVAL_SECONDS
    while time.monotonic() < deadline:
        _check_cancelled(cancel_event)
        try:
            # status_url is the backend's own data-plane endpoint from the signed run payload, not user input.
            # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            with opener(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
                if _is_arrow(response):
                    return _read_table(response), None
                # 202 — still running.
        except urllib.error.HTTPError as exc:
            if expect_object and exc.code == 302:
                return _fetch_presigned_table(exc.headers.get("Location") or "")
            raise DataPlaneError(_error_detail(exc)) from exc
        except urllib.error.URLError as exc:
            raise DataPlaneError(f"Could not reach the data plane: {exc.reason}") from exc
        except pa.ArrowInvalid as exc:
            raise DataPlaneError(f"Invalid Arrow response from the data plane: {exc}") from exc
        # An Event.wait doubles as an interruptible sleep: a cancel fires mid-interval.
        if cancel_event is not None:
            cancel_event.wait(interval)
        else:
            time.sleep(interval)
        interval = min(interval * 1.5, _POLL_MAX_INTERVAL_SECONDS)
    raise DataPlaneError("Timed out waiting for the query to finish")


def _fetch_presigned_table(presigned_url: str) -> tuple["pa.Table", str]:
    """Download the frame object from the presigned URL — deliberately credential-free.

    The URL is its own short-lived authorization; the data-plane token must never reach
    the object-store host. Range-based resume of an interrupted download is deferred.
    Returns the table plus a truncated URL preview — never the full URL, which is a
    bearer secret and must not travel beyond this fetch.
    """
    if not presigned_url:
        raise DataPlaneError("Data plane redirect carried no download URL")
    source_preview = presigned_url[:_FRAME_SOURCE_PREVIEW_CHARS]
    request = urllib.request.Request(presigned_url, method="GET")
    try:
        # The URL comes from our own backend's redirect (minted after token verification),
        # never from user input.
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            return _read_table(response), source_preview
    except urllib.error.HTTPError as exc:
        raise DataPlaneError(f"Frame download failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise DataPlaneError(f"Could not reach the frame store: {exc.reason}") from exc
    except pa.ArrowInvalid as exc:
        raise DataPlaneError(f"Invalid Arrow bytes in the frame object: {exc}") from exc


def _is_arrow(response: Any) -> bool:
    return "arrow" in (response.headers.get("Content-Type") or "")


def _read_table(source: Any) -> "pa.Table":
    return pa.ipc.open_stream(source).read_all()


def decode_arrow_stream(source: Any) -> tuple[list[str], list[tuple[Any, ...]], list[list[str]]]:
    """Decode an Arrow IPC stream (file-like or bytes-like) into (columns, rows, types)."""
    return _table_to_rows_and_types(_read_table(source))


def _table_to_rows_and_types(table: "pa.Table") -> tuple[list[str], list[tuple[Any, ...]], list[list[str]]]:
    """Turn an Arrow table into (columns, rows, types).

    Types come from the `hogql_types` schema metadata the data plane attaches (the
    real ClickHouse type names); when absent they are approximated from the Arrow
    schema so the envelope always carries something usable for axis detection.
    """
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
