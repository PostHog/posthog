import json
from collections.abc import Iterable
from http import HTTPStatus
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import patch

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.trustradius.source import TrustradiusSource
from products.warehouse_sources.backend.temporal.data_imports.sources.trustradius.trustradius import (
    trustradius_source,
    validate_credentials,
)


def response(body: object, status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.reason = HTTPStatus(status).phrase
    result.url = "https://api.trustradius.com/v1/product-ids"
    result._content = json.dumps(body).encode()
    result.headers["Content-Type"] = "application/json"
    return result


@pytest.mark.parametrize(
    ("endpoint", "path", "row", "params"),
    [
        ("products", "product-ids", {"_id": "product-example", "slug": "example-product"}, {}),
        ("product_scores", "product-scores", {"id": "product-example", "reviewCount": 42}, {}),
        (
            "trustquotes",
            "trustquotes",
            {"id": "quote-example", "text": "An invented quote.", "created": "2025-01-01"},
            {"include-anonymous": ["true"]},
        ),
        ("tags", "tags", {"id": "tag-example", "name": "Example tag"}, {}),
    ],
)
@pytest.mark.parametrize("empty", [False, True])
def test_full_refresh_selects_rows_and_stops_after_one_request(
    endpoint: str, path: str, row: dict[str, Any], params: dict[str, list[str]], empty: bool
) -> None:
    rows = [] if empty else [row]
    body = {"products": rows} if endpoint == "product_scores" else rows
    with patch("requests.adapters.HTTPAdapter.send", return_value=response(body)) as send:
        result = trustradius_source("example-secret", endpoint, 1, "test-job")
        assert [item for page in cast(Iterable[Any], result.items()) for item in page] == rows

    send.assert_called_once()
    request = send.call_args.args[0]
    assert request.method.upper() == "GET"
    assert urlsplit(request.url).path == f"/v1/{path}"
    assert parse_qs(urlsplit(request.url).query) == params
    assert request.headers["x-api-key"] == "example-secret"
    assert request.headers["Accept"] == "application/json"
    assert "example-secret" not in request.url
    assert send.call_args.kwargs["timeout"] == (10, 60)


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (200, [], (True, None)),
        (
            401,
            {
                "name": "NotAuthorized",
                "status": 401,
                "message": "You are not authorized to access Unable to verify your identity, please check that your API key is valid",
            },
            (
                False,
                "TrustRadius rejected your API key. Check the key with your TrustRadius Client Success Manager.",
            ),
        ),
        (
            403,
            {"message": "Forbidden"},
            (
                False,
                "TrustRadius denied access. Ask your Client Success Manager to check your API license and permissions.",
            ),
        ),
    ],
)
def test_validate_credentials_uses_one_request_and_maps_auth_errors(
    status: int, body: object, expected: tuple[bool, str | None]
) -> None:
    with patch("requests.adapters.HTTPAdapter.send", return_value=response(body, status)) as send:
        assert validate_credentials("example-secret") == expected
    send.assert_called_once()
    request = send.call_args.args[0]
    assert request.url == "https://api.trustradius.com/v1/product-ids"
    assert request.headers["x-api-key"] == "example-secret"


@pytest.mark.parametrize("status", [400, 404])
def test_validation_does_not_mislabel_other_errors(status: int) -> None:
    with patch("requests.adapters.HTTPAdapter.send", return_value=response({}, status)) as send:
        with pytest.raises(HTTPError):
            validate_credentials("example-secret")
    send.assert_called_once()


@pytest.mark.parametrize("status", [401, 403])
def test_sync_auth_errors_match_terminal_messages(status: int) -> None:
    with patch("requests.adapters.HTTPAdapter.send", return_value=response({}, status)) as send:
        with pytest.raises(HTTPError) as error:
            list(cast(Iterable[Any], trustradius_source("example-secret", "products", 1, "test-job").items()))
    send.assert_called_once()
    messages = TrustradiusSource().get_non_retryable_errors()
    assert len([message for pattern, message in messages.items() if pattern in str(error.value)]) == 1


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_failures_retry_and_keep_auth(status: int) -> None:
    with patch("requests.adapters.HTTPAdapter.send", side_effect=[response({}, status), response([])]) as send:
        assert list(cast(Iterable[Any], trustradius_source("example-secret", "products", 1, "test-job").items())) == []
    assert send.call_count == 2
    assert all(call.args[0].headers["x-api-key"] == "example-secret" for call in send.call_args_list)


@pytest.mark.parametrize("endpoint", ["products", "product_scores", "trustquotes", "tags"])
def test_unexpected_response_shape_fails_instead_of_erasing_table(endpoint: str) -> None:
    with patch("requests.adapters.HTTPAdapter.send", return_value=response({"unexpected": []})) as send:
        with pytest.raises(ValueError, match="Required"):
            list(cast(Iterable[Any], trustradius_source("example-secret", endpoint, 1, "test-job").items()))
    send.assert_called_once()


def test_unknown_endpoint_fails_before_request() -> None:
    with patch("requests.adapters.HTTPAdapter.send") as send:
        with pytest.raises(UnknownResourceError):
            trustradius_source("example-secret", "unknown", 1, "test-job")
    send.assert_not_called()
