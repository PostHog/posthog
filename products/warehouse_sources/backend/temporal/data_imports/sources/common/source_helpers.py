"""Shared helpers for source credential validation.

Most API sources implement `validate_credentials` by probing one cheap endpoint and mapping the HTTP
status to a bool. Centralize that probe so sources don't each re-implement the try/except + status
check (and so the 401-vs-403 distinction the skill describes is handled consistently).
"""

from collections.abc import Callable, Mapping

import requests
from requests.auth import AuthBase


def validate_via_probe(
    session_factory: Callable[[], requests.Session],
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    auth: AuthBase | None = None,
    ok_statuses: tuple[int, ...] = (200,),
    timeout: float = 10.0,
) -> tuple[bool, int | None]:
    """Probe ``url`` with a GET and report ``(is_valid, status_code)``.

    ``session_factory`` should return a tracked session (``make_tracked_session``). ANY failure
    building the session or making the request (transport error, and defensively anything else) maps
    to ``(False, None)`` — a credential probe should never raise out of ``validate_credentials`` and
    fail source creation; an unreachable/erroring probe just means "not validated". This matches the
    broad ``except Exception`` the hand-rolled probes across ~all sources use, so it's a drop-in.
    Any HTTP response maps to ``(status in ok_statuses, status)`` so the caller can distinguish 401
    (bad token) from 403 (valid token, missing scope) — accept 403 at source-create when
    ``schema_name`` is None, per the skill. The caller wraps the result into the ``(bool, message)``
    its ``validate_credentials`` returns.
    """
    try:
        session = session_factory()
        response = session.get(url, headers=dict(headers) if headers else None, auth=auth, timeout=timeout)
    except Exception:  # noqa: BLE001 — a credential probe must never raise; any failure means "not validated"
        return False, None
    return response.status_code in ok_statuses, response.status_code
