import json
from collections.abc import Iterable, Iterator
from http import HTTPStatus
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from requests import Request, Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.acast.acast import (
    acast_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.acast.source import AcastSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse


def items(response: SourceResponse) -> Iterable[Any]:
    return cast(Iterable[Any], response.items())


def response(body: object, status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.reason = HTTPStatus(status).phrase
    result.url = "https://open.acast.com/rest/shows"
    result.headers["Content-Type"] = "application/json"
    result._content = json.dumps(body).encode()
    return result


@pytest.fixture
def http_session() -> Iterator[MagicMock]:
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
    ) as factory:
        session = factory.return_value
        session.headers = {}
        session.prepare_request.side_effect = Request.prepare
        yield session


@pytest.mark.parametrize("rows", [[], [{"_id": "show-1"}], [{"_id": "show-1"}, {"_id": "show-2"}]])
def test_shows_full_refresh_stops_after_one_response(http_session: MagicMock, rows: list[dict[str, str]]) -> None:
    http_session.send.side_effect = [response(rows)]

    result = acast_source("fake-acast-key", "shows", 1, "job-1")
    assert [row for batch in items(result) for row in batch] == rows
    http_session.send.assert_called_once()
    request = http_session.send.call_args.args[0]
    assert request.method == "GET"
    assert request.url == "https://open.acast.com/rest/shows"
    assert request.headers["X-API-Key"] == "fake-acast-key"
    assert "Authorization" not in request.headers


def test_episode_fanout_keeps_parent_keys_and_continues_after_empty_show(http_session: MagicMock) -> None:
    http_session.send.side_effect = [
        response([{"_id": "show-1"}, {"_id": "show-2"}, {"_id": "show-3"}]),
        response([{"_id": "episode-1", "title": "First episode", "Markers": []}]),
        response([]),
        response([{"_id": "episode-1", "title": "Another episode", "Markers": []}]),
    ]

    result = acast_source("fake-acast-key", "episodes", 1, "job-1")
    rows = [row for batch in items(result) for row in batch]

    assert rows == [
        {"_id": "episode-1", "title": "First episode", "Markers": [], "show_id": "show-1"},
        {"_id": "episode-1", "title": "Another episode", "Markers": [], "show_id": "show-3"},
    ]
    assert result.primary_keys is not None
    assert len({tuple(row[key] for key in result.primary_keys) for row in rows}) == 2
    requests = [call.args[0] for call in http_session.send.call_args_list]
    assert [request.url for request in requests] == [
        "https://open.acast.com/rest/shows",
        "https://open.acast.com/rest/shows/show-1/episodes",
        "https://open.acast.com/rest/shows/show-2/episodes",
        "https://open.acast.com/rest/shows/show-3/episodes",
    ]
    assert all(request.headers["X-API-Key"] == "fake-acast-key" for request in requests)


def test_episodes_with_no_shows_make_no_child_requests(http_session: MagicMock) -> None:
    http_session.send.side_effect = [response([])]

    assert list(items(acast_source("fake-acast-key", "episodes", 1, "job-1"))) == []
    http_session.send.assert_called_once()


@pytest.mark.parametrize(
    ("status", "message", "expected"),
    [
        (200, "", (True, None)),
        (
            401,
            "Authentication required",
            (False, "Acast rejected the API key. Contact Acast Customer Success to check or replace the key."),
        ),
        (
            403,
            "Forbidden",
            (False, "Acast denied access. Ask Acast Customer Success to check the shows assigned to your API key."),
        ),
    ],
)
def test_credential_validation_maps_auth_errors(
    http_session: MagicMock, status: int, message: str, expected: tuple[bool, str | None]
) -> None:
    http_session.send.side_effect = [
        response([] if status == 200 else {"statusCode": status, "message": message}, status)
    ]

    assert validate_credentials("fake-acast-key", 1) == expected
    http_session.send.assert_called_once()
    request = http_session.send.call_args.args[0]
    assert request.url == "https://open.acast.com/rest/shows"
    assert request.headers["X-API-Key"] == "fake-acast-key"


@pytest.mark.parametrize("status", [401, 403, 404])
def test_sync_errors_are_not_retried_and_auth_errors_match_user_messages(http_session: MagicMock, status: int) -> None:
    http_session.send.side_effect = [response({"statusCode": status}, status)]

    with pytest.raises(HTTPError) as error:
        list(items(acast_source("fake-acast-key", "shows", 1, "job-1")))

    http_session.send.assert_called_once()
    matches = [
        message for pattern, message in AcastSource().get_non_retryable_errors().items() if pattern in str(error.value)
    ]
    assert len(matches) == (0 if status == 404 else 1)
    assert "fake-acast-key" not in str(error.value)


def test_credential_validation_propagates_other_errors(http_session: MagicMock) -> None:
    http_session.send.side_effect = [response({"statusCode": 404}, 404)]

    with pytest.raises(HTTPError):
        validate_credentials("fake-acast-key", 1)


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_errors_use_framework_retries(http_session: MagicMock, status: int) -> None:
    failed_response = response({"statusCode": status}, status)
    failed_response.headers["Retry-After"] = "0"
    http_session.send.side_effect = [failed_response, response([{"_id": "show-1"}])]

    with patch("time.sleep"):
        rows = [row for batch in items(acast_source("fake-acast-key", "shows", 1, "job-1")) for row in batch]

    assert rows == [{"_id": "show-1"}]
    assert http_session.send.call_count == 2


def test_unexpected_response_shape_fails_instead_of_importing_an_error(http_session: MagicMock) -> None:
    http_session.send.side_effect = [response({"error": "Unexpected response"})]

    with pytest.raises(ValueError, match="Required a list response body"):
        list(items(acast_source("fake-acast-key", "shows", 1, "job-1")))


def test_unknown_table_fails_before_making_requests(http_session: MagicMock) -> None:
    with pytest.raises(UnknownResourceError):
        acast_source("fake-acast-key", "unknown", 1, "job-1")

    http_session.send.assert_not_called()
