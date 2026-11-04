"""Shared helpers for source credential validation.

Most API sources implement `validate_credentials` by probing one cheap endpoint and mapping the HTTP
status to a bool. Centralize that probe so sources don't each re-implement the try/except + status
check (and so the 401-vs-403 distinction the skill describes is handled consistently).
"""

from collections.abc import Callable, Mapping

import requests
from requests.auth import AuthBase

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAuth2AuthRequestError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)

_UNREACHABLE_ERRORS: tuple[type[BaseException], ...] = (
    requests.ConnectionError,
    requests.Timeout,
    requests.exceptions.ChunkedEncodingError,
    RESTClientRetryableError,
)


def unreachable_vendor_message(vendor: str) -> str:
    """The `validate_credentials` message for a probe that got no usable answer from the vendor.

    It must not say that the credentials are invalid, because nothing proved that."""
    return f"Couldn't reach {vendor} to check your credentials. Try again in a few minutes."


def probe_status_message(vendor: str, status_code: int | None) -> str | None:
    """A fallback message for an HTTP status that a probe has no own message for. `None` means that the
    status says nothing about the credentials, so the probe must decide."""
    if status_code == 401:
        return f"{vendor} rejected the credentials. Check them and try again."
    if status_code == 403:
        return f"{vendor} denied access. Check that the credentials have the permissions this source needs."
    if status_code is not None and (status_code == 429 or status_code >= 500):
        return unreachable_vendor_message(vendor)
    return None


def is_unreachable_vendor_error(error: BaseException) -> bool:
    """Whether a probe error means only that the vendor gave no usable answer: a dropped connection, a
    timeout, a server error or a rate limit. Follows `raise ... from` causes, because many sources wrap
    the transport error in their own. Also follows the implicit context of an error raised inside an
    `except` block without `from`, unless `from None` suppressed it."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, _UNREACHABLE_ERRORS):
            return True
        if isinstance(current, requests.HTTPError) and current.response is not None:
            status = current.response.status_code
            if status == 429 or status >= 500:
                return True
        if isinstance(current, OAuth2AuthRequestError) and not current.is_permanent:
            return True
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    return False


def validate_via_probe(
    session_factory: Callable[[], requests.Session],
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    auth: AuthBase | None = None,
    ok_statuses: tuple[int, ...] = (200,),
    timeout: float = 10.0,
    allow_redirects: bool = True,
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

    Pass ``allow_redirects=False`` when the probe sends credentials via custom (non-``Authorization``)
    headers: ``requests`` does not strip those on a cross-origin redirect, so following one would
    replay the secret to the redirect's ``Location``.
    """
    try:
        session = session_factory()
        response = session.get(
            url,
            headers=dict(headers) if headers else None,
            auth=auth,
            timeout=timeout,
            allow_redirects=allow_redirects,
        )
    except Exception:  # noqa: BLE001 — a credential probe must never raise; any failure means "not validated"
        return False, None
    return response.status_code in ok_statuses, response.status_code
