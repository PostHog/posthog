"""Per-run execution: fetch the data, build the envelope, deliver the callback.

For the current Journey 1 scope every node is a pure-HogQL display node, so a run
is a capped-page fetch through the data plane — the ipykernel is not involved
(see sql_v2_kernel_architecture.md, "division of labor").
"""

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from . import envelope

logger = logging.getLogger(__name__)

_CALLBACK_TIMEOUT_SECONDS = 15
_DEFAULT_PAGE_LIMIT = 50


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


def _build_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    from . import data_plane  # noqa: PLC0415 — see _fetch_capped_page

    try:
        page = _fetch_capped_page(payload, limit=int(payload.get("page_limit") or _DEFAULT_PAGE_LIMIT), offset=0)
        return envelope.from_columns_and_rows(page["columns"], page["rows"], page["types"], page["has_more"])
    except data_plane.DataPlaneError as exc:
        return envelope.from_error(str(exc))
    except Exception as exc:  # noqa: BLE001 — any failure must still produce a callback
        return envelope.from_error(f"Run failed in the sandbox: {exc}")


def fetch_page(payload: dict[str, Any]) -> dict[str, Any]:
    """Serve a /page request: a bounded synchronous re-query, not a run (no callback).

    Raises DataPlaneError for user-facing query errors; the server maps it to a 400.
    """
    page = _fetch_capped_page(
        payload,
        limit=int(payload.get("limit") or _DEFAULT_PAGE_LIMIT),
        offset=int(payload.get("offset") or 0),
    )
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
        # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected — url is the backend's
        # own callback endpoint from the signed run payload, never user-controlled.
        urllib.request.urlopen(request, timeout=_CALLBACK_TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001 — best-effort; the backend watchdog covers a lost callback
        logger.exception("nb_kernel callback delivery failed")
