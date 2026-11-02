from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ticketmaster import (
    TicketmasterSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ticketmaster.source import TicketmasterSource
from products.warehouse_sources.backend.temporal.data_imports.sources.ticketmaster.ticketmaster import (
    validate_credentials,
)

UNREACHABLE_MESSAGE = "Couldn't reach Ticketmaster to check your credentials. Try again in a few minutes."


def make_config(keyword: str = " Example act ") -> TicketmasterSourceConfig:
    return TicketmasterSourceConfig(api_key="fake-ticketmaster-key", keyword=keyword)


def make_page(endpoint: str, number: int, count: int, total: int) -> dict[str, Any]:
    return {
        "_embedded": {endpoint: [{"id": f"item-{number * 200 + i}"} for i in range(count)]},
        "page": {"number": number, "size": 200, "totalElements": total, "totalPages": (total + 199) // 200},
    }


def read_rows(
    endpoint: str, script: Script, keyword: str = " Example act ", config: TicketmasterSourceConfig | None = None
) -> DriveResult:
    return SourceDriver(TicketmasterSource(), config or make_config(keyword)).run(endpoint, script)


@pytest.mark.parametrize("total", [1000, 1001])
def test_search_limit_never_truncates(total: int) -> None:
    result = read_rows("events", [ScriptedResponse(json=make_page("events", page, 200, total)) for page in range(5)])

    if total > 1000:
        assert isinstance(result.raised, ValueError)
        assert "exceeds 1,000 results" in str(result.raised)
        assert str(result.raised) in TicketmasterSource().get_non_retryable_errors()
        assert len(result.requests) == 1
        assert result.saved_states == []
    else:
        assert result.raised is None
        assert len(result.rows) == 1000
        assert len(result.requests) == 5


@pytest.mark.parametrize(
    "body, message",
    [
        ({"fault": {"faultstring": "Unexpected response"}}, "invalid pagination data"),
        ({"page": {"totalElements": 1, "totalPages": 1}}, "empty page before the search ended"),
        ({"page": {"totalElements": "1", "totalPages": 1}}, "invalid pagination data"),
    ],
)
def test_malformed_response_fails_instead_of_erasing_data(body: dict[str, Any], message: str) -> None:
    result = read_rows("events", [ScriptedResponse(json=body)])

    assert isinstance(result.raised, ValueError)
    assert message in str(result.raised)
    assert len(result.requests) == 1


@pytest.mark.parametrize("status", [401, 403])
def test_auth_errors_are_permanent_and_hide_secrets(status: int) -> None:
    result = read_rows(
        "events",
        [
            ScriptedResponse(
                status=status,
                json={"fault": {"faultstring": "Invalid ApiKey", "detail": {"errorcode": "oauth.v2.InvalidApiKey"}}},
            )
        ],
    )

    assert isinstance(result.raised, ValueError)
    message = str(result.raised)
    assert message in TicketmasterSource().get_non_retryable_errors()
    assert "fake-ticketmaster-key" not in message
    assert len(result.requests) == 1


@pytest.mark.parametrize("status", [400, 404])
def test_client_errors_hide_query_key(status: int) -> None:
    config = TicketmasterSourceConfig(api_key="secret/key?", keyword="Example act")
    result = read_rows("events", [ScriptedResponse(status=status)], config=config)

    assert isinstance(result.raised, ValueError)
    assert f"HTTP {status}" in str(result.raised)
    assert "secret/key?" not in str(result.raised)
    assert "apikey" not in str(result.raised)
    assert len(result.requests) == 1


@pytest.mark.parametrize(
    "status,expected_message",
    [
        (429, UNREACHABLE_MESSAGE),
        (503, UNREACHABLE_MESSAGE),
        (404, "Ticketmaster request failed (HTTP 404)."),
    ],
)
def test_credential_probe(status: int, expected_message: str) -> None:
    with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
        assert validate_credentials(make_config(), "venues", "v2") == (False, expected_message)
    assert {request.path for request in network.requests_log} == {"/discovery/v2/venues.json"}
    for request in network.requests_log:
        assert request.query == {
            "apikey": ("fake-ticketmaster-key",),
            "size": ("1",),
            "keyword": ("Example act",),
        }


@pytest.mark.parametrize("keyword", ["", "   "])
def test_blank_keyword_rejected_before_request(keyword: str) -> None:
    with scripted_network([]) as network:
        assert validate_credentials(make_config(keyword), "events", "v2") == (
            False,
            "Enter a search keyword to limit the Ticketmaster results.",
        )
    result = read_rows("events", [], keyword)

    assert isinstance(result.raised, ValueError)
    assert "Enter a search keyword" in str(result.raised)
    assert network.requests_log == []
    assert result.requests == []


def test_unknown_endpoint_rejected_before_request() -> None:
    result = read_rows("../unknown", [])

    assert isinstance(result.raised, UnknownResourceError)
    assert result.requests == []


@pytest.mark.parametrize("error", [ConnectionResetError("reset"), TimeoutError("timed out")])
def test_credential_connection_error_gives_a_message(error: BaseException) -> None:
    with scripted_network(always(error)):
        assert validate_credentials(make_config(), "events", "v2") == (False, UNREACHABLE_MESSAGE)
