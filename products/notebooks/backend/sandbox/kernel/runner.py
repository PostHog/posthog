"""Per-run execution: fetch the data, build the envelope, deliver the callback.

For the current Journey 1/2 scope every node is a pure-HogQL display node, so a
run is a capped fetch through the data plane — the ipykernel is not involved
(see sql_v2_kernel_architecture.md, "division of labor").

A run fetches up to `cache_limit` rows in one ClickHouse query and keeps them in
an in-memory per-run cache; `/page` requests within the cache are local slices
(no ClickHouse work, no held backend workers). Only paging beyond the cache — or
after a kernel restart emptied it — re-queries the data plane with LIMIT/OFFSET.
This is the capped, memory-resident precursor of the file-backed result store in
sql_v2_kernel_architecture.md.
"""

import json
import logging
import threading
import urllib.error
import urllib.request
from collections import OrderedDict
from typing import Any

from . import envelope

logger = logging.getLogger(__name__)

_CALLBACK_TIMEOUT_SECONDS = 15
_DEFAULT_PAGE_LIMIT = 50
_DEFAULT_CACHE_LIMIT = 300
_MAX_CACHED_RESULTS = 20

# run_id -> {columns, types, rows (json-safe), complete}; complete means the cache
# holds the query's entire result, not just the first cache_limit rows.
_result_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
_result_cache_lock = threading.Lock()


def execute_run(payload: dict[str, Any]) -> None:
    """Entry point for a /run request, invoked on a background thread."""
    result = _build_envelope(payload)
    _post_callback(payload["callback_url"], payload["callback_token"], result)


def _fetch_capped_page(payload: dict[str, Any], limit: int, offset: int) -> dict[str, Any]:
    """Fetch limit+1 rows through the data plane; the extra row only signals has_more."""
    # Deferred so a broken pyarrow install degrades to a per-run error envelope
    # instead of preventing the server from starting.
    from . import data_plane  # noqa: PLC0415

    columns, rows, types = data_plane.fetch_query_page(
        payload["data_plane_url"],
        payload["data_plane_token"],
        payload["code"],
        limit=limit + 1,
        offset=offset,
    )
    has_more = len(rows) > limit
    return {"columns": columns, "rows": rows[:limit], "types": types, "has_more": has_more}


def _cache_result(
    run_id: str, columns: list[str], types: list[list[str]], rows: list[list[Any]], complete: bool
) -> None:
    with _result_cache_lock:
        _result_cache[run_id] = {"columns": columns, "types": types, "rows": rows, "complete": complete}
        _result_cache.move_to_end(run_id)
        while len(_result_cache) > _MAX_CACHED_RESULTS:
            _result_cache.popitem(last=False)


def _cached_page(run_id: str, offset: int, limit: int) -> dict[str, Any] | None:
    """Slice a page out of the cached result, or None if the cache can't serve it."""
    with _result_cache_lock:
        entry = _result_cache.get(run_id)
        if entry is None:
            return None
        _result_cache.move_to_end(run_id)
    rows = entry["rows"]
    end = offset + limit
    # A page that runs past an incomplete cache needs rows we don't have — re-query.
    if not entry["complete"] and end > len(rows):
        return None
    return {
        "columns": entry["columns"],
        "types": entry["types"],
        "rows": rows[offset:end],
        "has_more": end < len(rows) or not entry["complete"],
    }


def _build_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    from . import data_plane  # noqa: PLC0415 — see _fetch_capped_page

    page_limit = int(payload.get("page_limit") or _DEFAULT_PAGE_LIMIT)
    cache_limit = max(int(payload.get("cache_limit") or _DEFAULT_CACHE_LIMIT), page_limit)
    try:
        result = _fetch_capped_page(payload, limit=cache_limit, offset=0)
        rows = envelope.json_safe_rows(result["rows"])
        run_id = str(payload.get("run_id") or "")
        if run_id:
            _cache_result(run_id, result["columns"], result["types"], rows, complete=not result["has_more"])
        return envelope.from_columns_and_rows(
            result["columns"],
            result["rows"][:page_limit],
            result["types"],
            has_more=result["has_more"] or len(rows) > page_limit,
        )
    except data_plane.DataPlaneError as exc:
        return envelope.from_error(str(exc))
    except Exception as exc:  # noqa: BLE001 — any failure must still produce a callback
        return envelope.from_error(f"Run failed in the sandbox: {exc}")


def fetch_page(payload: dict[str, Any]) -> dict[str, Any]:
    """Serve a /page request: a cached local slice, or a bounded synchronous re-query.

    Raises DataPlaneError for user-facing query errors; the server maps it to a 400.
    """
    offset = int(payload.get("offset") or 0)
    limit = int(payload.get("limit") or _DEFAULT_PAGE_LIMIT)

    cached = _cached_page(str(payload.get("run_id") or ""), offset, limit)
    if cached is not None:
        return cached

    page = _fetch_capped_page(payload, limit=limit, offset=offset)
    return {
        "columns": page["columns"],
        "types": page["types"],
        "rows": envelope.json_safe_rows(page["rows"]),
        "has_more": page["has_more"],
    }


def _post_callback(callback_url: str, callback_token: str, result: dict[str, Any]) -> None:
    request = urllib.request.Request(
        callback_url,
        data=json.dumps({"envelope": result}).encode(),
        headers={"Authorization": f"Bearer {callback_token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected — url is the backend's
        # own callback endpoint from the signed run payload, never user-controlled.
        urllib.request.urlopen(request, timeout=_CALLBACK_TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001 — best-effort; the backend watchdog covers a lost callback
        logger.exception("nb_kernel callback delivery failed")
