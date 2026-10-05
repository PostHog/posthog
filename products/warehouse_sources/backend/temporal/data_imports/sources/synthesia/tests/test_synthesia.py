import json
from collections.abc import Iterable
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, patch

from requests import HTTPError, PreparedRequest, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.synthesia.source import SynthesiaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.synthesia.synthesia import (
    SynthesiaResumeConfig,
    synthesia_source,
    validate_credentials,
)


def make_response(body: dict[str, Any], status: int = 200) -> Response:
    response = Response()
    response.status_code = status
    response.reason = {401: "Unauthorized", 403: "Forbidden"}.get(status, "Test response")
    response._content = json.dumps(body).encode()
    response.headers["Content-Type"] = "application/json"
    response.url = "https://api.synthesia.io/v2/videos"
    return response


@pytest.fixture
def manager() -> MagicMock:
    result = MagicMock(spec=ResumableSourceManager)
    result.can_resume.return_value = False
    return result


@pytest.mark.parametrize("endpoint", ["videos", "templates", "webhooks"])
def test_pagination_uses_returned_offset_and_raw_auth(endpoint: str, manager: MagicMock) -> None:
    rows = [{"id": "item-1", "createdAt": 1700000000}, {"id": "item-2", "createdAt": 1700000001}]
    responses = [make_response({endpoint: [rows[0]], "nextOffset": 37}), make_response({endpoint: [rows[1]]})]
    with patch("requests.Session.send", side_effect=responses) as send:
        result = synthesia_source("fake-api-key", "v2", endpoint, 1, "job", manager)
        pages = list(cast(Iterable[list[dict[str, Any]]], result.items()))

    assert pages == [[rows[0]], [rows[1]]]
    for call, offset in zip(send.call_args_list, ["0", "37"], strict=True):
        request: PreparedRequest = call.args[0]
        assert call.kwargs["timeout"] == (10.0, 60.0)
        assert request.method == "GET"
        assert request.headers["Authorization"] == "fake-api-key"
        url = urlsplit(cast(str, request.url))
        assert (url.scheme, url.netloc, url.path) == ("https", "api.synthesia.io", f"/v2/{endpoint}")
        assert parse_qs(url.query) == {"limit": ["100"], "offset": [offset]}
    manager.save_state.assert_called_once_with(SynthesiaResumeConfig(next_offset=37))
    manager.clear_state.assert_not_called()
    assert result.on_complete is not None
    result.on_complete()
    manager.clear_state.assert_called_once()


@pytest.mark.parametrize(
    "body",
    [
        {"videos": []},
        {"videos": [{"id": "last"}]},
        {"videos": [{"id": "last"}], "nextOffset": None},
        {"videos": [{"id": "last"}], "nextOffset": 0},
    ],
)
def test_terminal_page_stops_without_saving_cursor(body: dict[str, Any], manager: MagicMock) -> None:
    with patch("requests.Session.send", return_value=make_response(body)) as send:
        result = synthesia_source("fake-api-key", "v2", "videos", 1, "job", manager)
        pages = list(cast(Iterable[list[dict[str, Any]]], result.items()))
    assert [row for page in pages for row in page] == body["videos"]
    send.assert_called_once()
    manager.save_state.assert_not_called()


@pytest.mark.parametrize("saved_offset", [None, 123])
def test_resume_starts_at_saved_offset(saved_offset: int | None, manager: MagicMock) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = SynthesiaResumeConfig(next_offset=saved_offset) if saved_offset else None
    with patch("requests.Session.send", return_value=make_response({"videos": []})) as send:
        result = synthesia_source("fake-api-key", "v2", "videos", 1, "job", manager)
        list(cast(Iterable[Any], result.items()))
    query = parse_qs(urlsplit(send.call_args.args[0].url).query)
    assert query["offset"] == [str(saved_offset or 0)]


def test_repeated_offset_fails_instead_of_looping(manager: MagicMock) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = SynthesiaResumeConfig(next_offset=12)
    with patch("requests.Session.send", return_value=make_response({"videos": [{"id": "v"}], "nextOffset": 12})):
        result = synthesia_source("fake-api-key", "v2", "videos", 1, "job", manager)
        with pytest.raises(ValueError, match="repeated cursor"):
            list(cast(Iterable[Any], result.items()))
    manager.save_state.assert_not_called()


def test_webhook_signing_secrets_are_not_imported(manager: MagicMock) -> None:
    row = {"id": "hook-1", "secret": "fake-signing-secret", "url": "https://example.com/hook", "status": "active"}
    with patch("requests.Session.send", return_value=make_response({"webhooks": [row]})):
        result = synthesia_source("fake-api-key", "v2", "webhooks", 1, "job", manager)
        pages = list(cast(Iterable[Any], result.items()))
    assert pages == [[{"id": "hook-1", "url": "https://example.com/hook", "status": "active"}]]


@pytest.mark.parametrize("status", [200, 401, 403, 404, 429, 500])
def test_credential_status_mapping(status: int) -> None:
    with patch("requests.Session.send", return_value=make_response({"videos": []}, status)) as send:
        if status in (200, 401, 403):
            valid, message = validate_credentials("fake-api-key", "v2")
            assert valid is (status == 200)
            if status == 200:
                assert message is None
            else:
                assert message is not None and "Legacy (v2)" in message
        else:
            with pytest.raises(HTTPError):
                validate_credentials("fake-api-key", "v2")
    send.assert_called_once()
    request = send.call_args.args[0]
    assert request.headers["Authorization"] == "fake-api-key"
    assert parse_qs(urlsplit(request.url).query) == {"limit": ["1"]}


@pytest.mark.parametrize("status", [401, 403])
def test_sync_auth_errors_are_terminal_and_mapped(status: int, manager: MagicMock) -> None:
    body = {"context": "User is not authenticated", "error": "Forbidden"}
    with patch("requests.Session.send", return_value=make_response(body, status)) as send:
        result = synthesia_source("fake-api-key", "v2", "videos", 1, "job", manager)
        with pytest.raises(HTTPError) as error:
            list(cast(Iterable[Any], result.items()))
    send.assert_called_once()
    messages = [
        message
        for pattern, message in SynthesiaSource().get_non_retryable_errors().items()
        if pattern in str(error.value)
    ]
    assert len(messages) == 1
    assert messages[0] is not None and "Legacy (v2)" in messages[0]


@pytest.mark.parametrize("status", [429, 503])
def test_sync_transient_errors_retry(status: int, manager: MagicMock) -> None:
    responses = [make_response({"error": "temporary"}, status), make_response({"videos": [{"id": "v"}]})]
    with patch("requests.Session.send", side_effect=responses) as send, patch("time.sleep"):
        result = synthesia_source("fake-api-key", "v2", "videos", 1, "job", manager)
        assert list(cast(Iterable[Any], result.items())) == [[{"id": "v"}]]
    assert send.call_count == 2


def test_unknown_endpoint_fails_before_request(manager: MagicMock) -> None:
    with patch("requests.Session.send") as send:
        with pytest.raises(UnknownResourceError):
            synthesia_source("fake-api-key", "v2", "unknown", 1, "job", manager)
    send.assert_not_called()


def test_missing_list_fails_instead_of_replacing_table_with_empty_data(manager: MagicMock) -> None:
    with patch("requests.Session.send", return_value=make_response({"unexpected": []})):
        result = synthesia_source("fake-api-key", "v2", "videos", 1, "job", manager)
        with pytest.raises(ValueError):
            list(cast(Iterable[Any], result.items()))
