"""Calls to the control plane for the console, with failures mapped to facade errors."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import requests

from products.managed_warehouse.backend.facade.contracts import (
    ControlPlaneNotConfiguredError,
    ControlPlaneRejectedError,
    ControlPlaneUnavailableError,
    ControlPlaneUpstreamError,
    WarehouseNotFoundError,
)
from products.managed_warehouse.backend.presentation import hogtower

MAX_FORWARDED_MESSAGE_LENGTH = 200


@contextmanager
def malformed_body_guard() -> Iterator[None]:
    """Turn a control plane body of an unexpected shape into the upstream error, not a 500.

    ``from None`` keeps the original exception, and the body in its frames, out of the chain that
    error reporting captures. A body can carry a password.
    """
    try:
        yield
    except (KeyError, TypeError, ValueError, ArithmeticError, AttributeError):
        raise ControlPlaneUpstreamError("The managed warehouse control plane sent an unexpected response") from None


def _forwardable_message(response: hogtower.TranslatedResponse) -> str | None:
    """The control plane's own error text, only when it is a short one-line string in a JSON object."""
    body = response.json()
    if not response.from_json or not isinstance(body, dict):
        return None
    message = body.get("error")
    if isinstance(message, str) and 0 < len(message) <= MAX_FORWARDED_MESSAGE_LENGTH and "\n" not in message:
        return message
    return None


def call_control_plane(
    send: Callable[[], hogtower.TranslatedResponse], *, not_found: type[Exception] = WarehouseNotFoundError
) -> dict[str, Any]:
    """Run one hogtower call and return its JSON object, or raise the matching facade error."""
    if not hogtower.is_configured():
        raise ControlPlaneNotConfiguredError("The managed warehouse control plane is not configured")
    try:
        response = send()
    except requests.RequestException as error:
        raise ControlPlaneUpstreamError("The managed warehouse control plane could not be reached") from error
    if response.status_code == 404:
        raise not_found("The control plane has no matching warehouse or query")
    if response.status_code == 503:
        raise ControlPlaneUnavailableError("The managed warehouse control plane is temporarily unavailable")
    if response.status_code in (400, 409, 422):
        message = _forwardable_message(response) or "The managed warehouse rejected the request"
        raise ControlPlaneRejectedError(message, status_code=400)
    body = response.json()
    if not response.ok or not isinstance(body, dict):
        raise ControlPlaneUpstreamError(f"The managed warehouse control plane answered {response.status_code}")
    return body
