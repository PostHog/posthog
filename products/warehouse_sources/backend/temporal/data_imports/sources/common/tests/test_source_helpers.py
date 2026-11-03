from typing import cast

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAuth2AuthRequestError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import (
    is_unreachable_vendor_error,
    probe_status_message,
)


def _http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"HTTP {status}", response=response)


def _wrapped(cause: BaseException) -> ValueError:
    try:
        raise ValueError("vendor client failed") from cause
    except ValueError as error:
        return error


def _implicitly_wrapped(context: BaseException) -> ValueError:
    try:
        try:
            raise context
        except type(context):
            raise ValueError("vendor client failed")  # noqa: B904 — the implicit context is the point
    except ValueError as error:
        return error


def _suppressed(context: BaseException) -> ValueError:
    try:
        try:
            raise context
        except type(context):
            raise ValueError("vendor client failed") from None
    except ValueError as error:
        return error


@pytest.mark.parametrize(
    "error,expected",
    [
        (requests.ConnectionError("refused"), True),
        (requests.Timeout("timed out"), True),
        (requests.exceptions.ChunkedEncodingError("cut"), True),
        (RESTClientRetryableError("HTTP 503"), True),
        (_http_error(500), True),
        (_http_error(429), True),
        (OAuth2AuthRequestError("HTTP 502 from the token endpoint"), True),
        (_wrapped(requests.ConnectionError("refused")), True),
        (_implicitly_wrapped(requests.ConnectionError("refused")), True),
        (_http_error(401), False),
        (_http_error(403), False),
        (_http_error(404), False),
        (requests.HTTPError("no response", response=cast(requests.Response, None)), False),
        (OAuth2AuthRequestError("invalid_client", is_permanent=True), False),
        (_wrapped(_http_error(400)), False),
        (_implicitly_wrapped(_http_error(400)), False),
        (_suppressed(requests.ConnectionError("refused")), False),
        (ValueError("bad config"), False),
    ],
)
def test_is_unreachable_vendor_error(error: BaseException, expected: bool) -> None:
    assert is_unreachable_vendor_error(error) is expected


@pytest.mark.parametrize(
    "status,expected",
    [
        (401, "Acme rejected the credentials. Check them and try again."),
        (403, "Acme denied access. Check that the credentials have the permissions this source needs."),
        (429, "Couldn't reach Acme to check your credentials. Try again in a few minutes."),
        (503, "Couldn't reach Acme to check your credentials. Try again in a few minutes."),
        (400, None),
        (None, None),
    ],
)
def test_probe_status_message(status: int | None, expected: str | None) -> None:
    assert probe_status_message("Acme", status) == expected
