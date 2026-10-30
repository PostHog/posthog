import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.acast.acast import validate_credentials
from products.warehouse_sources.backend.temporal.data_imports.sources.acast.source import AcastSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.acast import AcastSourceConfig


def acast_driver() -> SourceDriver:
    return SourceDriver(AcastSource(), AcastSourceConfig(api_key="fake-acast-key"))


def test_episode_fanout_keeps_parent_keys_and_continues_after_empty_show() -> None:
    result = acast_driver().run(
        "episodes",
        [
            ScriptedResponse(json=[{"_id": "show-1"}, {"_id": "show-2"}, {"_id": "show-3"}]),
            ScriptedResponse(json=[{"_id": "episode-1", "title": "First episode", "Markers": []}]),
            ScriptedResponse(json=[]),
            ScriptedResponse(json=[{"_id": "episode-1", "title": "Another episode", "Markers": []}]),
        ],
    )

    assert result.raised is None
    assert result.rows == [
        {"_id": "episode-1", "title": "First episode", "Markers": [], "show_id": "show-1"},
        {"_id": "episode-1", "title": "Another episode", "Markers": [], "show_id": "show-3"},
    ]
    assert result.response is not None
    assert result.response.primary_keys is not None
    assert len({tuple(row[key] for key in result.response.primary_keys) for row in result.rows}) == 2
    assert result.urls == [
        "https://open.acast.com/rest/shows",
        "https://open.acast.com/rest/shows/show-1/episodes",
        "https://open.acast.com/rest/shows/show-2/episodes",
        "https://open.acast.com/rest/shows/show-3/episodes",
    ]
    assert all(request.headers["x-api-key"] == "fake-acast-key" for request in result.requests)


@pytest.mark.parametrize(
    ("status", "message", "expected"),
    [
        (200, "", (True, None)),
    ],
)
def test_credential_validation_maps_auth_errors(status: int, message: str, expected: tuple[bool, str | None]) -> None:
    with scripted_network(
        [ScriptedResponse(status=status, json=[] if status == 200 else {"statusCode": status, "message": message})]
    ) as network:
        assert validate_credentials("fake-acast-key", 1) == expected

    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.url == "https://open.acast.com/rest/shows"
    assert request.headers["x-api-key"] == "fake-acast-key"


@pytest.mark.parametrize("status", [401, 403, 404])
def test_sync_errors_are_not_retried_and_auth_errors_match_user_messages(status: int) -> None:
    result = acast_driver().run("shows", [ScriptedResponse(status=status, json={"statusCode": status})])

    assert isinstance(result.raised, HTTPError)
    assert len(result.requests) == 1
    matches = [
        message
        for pattern, message in AcastSource().get_non_retryable_errors().items()
        if pattern in str(result.raised)
    ]
    assert len(matches) == (0 if status == 404 else 1)
    assert "fake-acast-key" not in str(result.raised)


def test_credential_validation_propagates_other_errors() -> None:
    with scripted_network([ScriptedResponse(status=404, json={"statusCode": 404})]) as network:
        with pytest.raises(HTTPError):
            validate_credentials("fake-acast-key", 1)

    assert len(network.requests_log) == 1


def test_unexpected_response_shape_fails_instead_of_importing_an_error() -> None:
    result = acast_driver().run("shows", [ScriptedResponse(json={"error": "Unexpected response"})])

    assert isinstance(result.raised, ValueError)
    assert "Required a list response body" in str(result.raised)
