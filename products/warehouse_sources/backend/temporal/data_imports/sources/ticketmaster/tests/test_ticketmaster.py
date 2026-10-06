from collections.abc import Iterable
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock, call

import requests_mock
from requests.exceptions import ConnectionError, HTTPError, RequestException, Timeout

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ticketmaster import (
    TicketmasterSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ticketmaster.source import TicketmasterSource
from products.warehouse_sources.backend.temporal.data_imports.sources.ticketmaster.ticketmaster import (
    TicketmasterResumeConfig,
    ticketmaster_source,
    validate_credentials,
)


def make_config(keyword: str = " Example act ") -> TicketmasterSourceConfig:
    return TicketmasterSourceConfig(api_key="fake-ticketmaster-key", keyword=keyword)


def make_manager(page: int | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = page is not None
    manager.load_state.return_value = TicketmasterResumeConfig(page=page) if page is not None else None
    return manager


def make_page(endpoint: str, number: int, count: int, total: int) -> dict[str, Any]:
    return {
        "_embedded": {endpoint: [{"id": f"item-{number * 200 + i}"} for i in range(count)]},
        "page": {"number": number, "size": 200, "totalElements": total, "totalPages": (total + 199) // 200},
    }


def read_rows(endpoint: str, manager: MagicMock, keyword: str = " Example act ") -> list[dict[str, Any]]:
    response = ticketmaster_source(make_config(keyword), endpoint, "v2", 1, "test-job", manager)
    return [row for batch in cast(Iterable[list[dict[str, Any]]], response.items()) for row in batch]


@pytest.mark.parametrize("endpoint", ["events", "attractions", "venues"])
@pytest.mark.parametrize("resume_page", [None, 1])
def test_pagination_auth_and_resume(endpoint: str, resume_page: int | None) -> None:
    manager = make_manager(resume_page)
    pages = [make_page(endpoint, 0, 200, 201), make_page(endpoint, 1, 1, 201)]
    with requests_mock.Mocker() as http:
        http.get(
            f"https://app.ticketmaster.com/discovery/v2/{endpoint}.json",
            [{"json": page} for page in pages[resume_page or 0 :]],
        )
        rows = read_rows(endpoint, manager)

    assert [row["id"] for row in rows] == [f"item-{i}" for i in range((resume_page or 0) * 200, 201)]
    assert len(http.request_history) == (1 if resume_page else 2)
    for number, request in enumerate(http.request_history, start=resume_page or 0):
        assert parse_qs(urlsplit(request.url).query) == {
            "apikey": ["fake-ticketmaster-key"],
            "keyword": ["Example act"],
            "size": ["200"],
            "page": [str(number)],
            "sort": ["name,asc"],
        }
        assert "Authorization" not in request.headers
    assert manager.save_state.call_args_list == ([] if resume_page else [call(TicketmasterResumeConfig(page=1))])


@pytest.mark.parametrize("embedded", [None, {"events": []}])
def test_empty_search_without_embedded_collection(embedded: dict[str, list[Any]] | None) -> None:
    body: dict[str, Any] = {"page": {"number": 0, "size": 200, "totalElements": 0, "totalPages": 0}}
    if embedded is not None:
        body["_embedded"] = embedded
    manager = make_manager()
    with requests_mock.Mocker() as http:
        http.get("https://app.ticketmaster.com/discovery/v2/events.json", json=body)
        assert read_rows("events", manager) == []
    assert http.call_count == 1
    manager.save_state.assert_not_called()


@pytest.mark.parametrize("total", [1000, 1001])
def test_search_limit_never_truncates(total: int) -> None:
    manager = make_manager()
    with requests_mock.Mocker() as http:
        http.get(
            "https://app.ticketmaster.com/discovery/v2/events.json",
            [{"json": make_page("events", page, 200, total)} for page in range(5)],
        )
        if total > 1000:
            with pytest.raises(ValueError, match="exceeds 1,000 results") as error:
                read_rows("events", manager)
            assert str(error.value) in TicketmasterSource().get_non_retryable_errors()
            assert http.call_count == 1
            manager.save_state.assert_not_called()
        else:
            assert len(read_rows("events", manager)) == 1000
            assert http.call_count == 5


@pytest.mark.parametrize(
    "body, message",
    [
        ({"fault": {"faultstring": "Unexpected response"}}, "invalid pagination data"),
        ({"page": {"totalElements": 1, "totalPages": 1}}, "empty page before the search ended"),
        ({"page": {"totalElements": "1", "totalPages": 1}}, "invalid pagination data"),
    ],
)
def test_malformed_response_fails_instead_of_erasing_data(body: dict[str, Any], message: str) -> None:
    with requests_mock.Mocker() as http:
        http.get("https://app.ticketmaster.com/discovery/v2/events.json", json=body)
        with pytest.raises(ValueError, match=message):
            read_rows("events", make_manager())
    assert http.call_count == 1


@pytest.mark.parametrize("status", [401, 403])
def test_auth_errors_are_permanent_and_hide_secrets(status: int) -> None:
    with requests_mock.Mocker() as http:
        http.get(
            "https://app.ticketmaster.com/discovery/v2/events.json",
            status_code=status,
            json={"fault": {"faultstring": "Invalid ApiKey", "detail": {"errorcode": "oauth.v2.InvalidApiKey"}}},
        )
        with pytest.raises(ValueError) as error:
            read_rows("events", make_manager())
    message = str(error.value)
    assert message in TicketmasterSource().get_non_retryable_errors()
    assert "fake-ticketmaster-key" not in message
    assert http.call_count == 1


@pytest.mark.parametrize("status", [400, 404])
def test_client_errors_hide_query_key(status: int) -> None:
    config = TicketmasterSourceConfig(api_key="secret/key?", keyword="Example act")
    with requests_mock.Mocker() as http:
        http.get("https://app.ticketmaster.com/discovery/v2/events.json", status_code=status)
        with pytest.raises(ValueError, match=f"HTTP {status}") as error:
            response = ticketmaster_source(config, "events", "v2", 1, "test-job", make_manager())
            list(cast(Iterable[Any], response.items()))
    assert "secret/key?" not in str(error.value)
    assert "apikey" not in str(error.value)
    assert http.call_count == 1


@pytest.mark.parametrize("status", [429, 503])
def test_transient_error_retries(status: int) -> None:
    with requests_mock.Mocker() as http:
        http.get(
            "https://app.ticketmaster.com/discovery/v2/events.json",
            [
                {"status_code": status, "headers": {"Retry-After": "0"}},
                {"json": make_page("events", 0, 1, 1)},
            ],
        )
        assert read_rows("events", make_manager()) == [{"id": "item-0"}]
    assert http.call_count == 2


@pytest.mark.parametrize("status", [200, 401, 403, 429, 503])
def test_credential_probe(status: int) -> None:
    with requests_mock.Mocker() as http:
        http.get("https://app.ticketmaster.com/discovery/v2/venues.json", status_code=status, json={})
        if status in (429, 503):
            with pytest.raises(HTTPError, match=f"HTTP {status}") as error:
                validate_credentials(make_config(), "venues", "v2")
            assert "fake-ticketmaster-key" not in str(error.value)
        else:
            valid, message = validate_credentials(make_config(), "venues", "v2")
            assert valid is (status == 200)
            if status == 200:
                assert message is None
            else:
                assert message in TicketmasterSource().get_non_retryable_errors()
    assert http.call_count == 1
    assert parse_qs(urlsplit(http.last_request.url).query) == {
        "apikey": ["fake-ticketmaster-key"],
        "size": ["1"],
        "keyword": ["Example act"],
    }


@pytest.mark.parametrize("keyword", ["", "   "])
def test_blank_keyword_rejected_before_request(keyword: str) -> None:
    with requests_mock.Mocker() as http:
        assert validate_credentials(make_config(keyword), "events", "v2") == (
            False,
            "Enter a search keyword to limit the Ticketmaster results.",
        )
        with pytest.raises(ValueError, match="Enter a search keyword"):
            read_rows("events", make_manager(), keyword)
    assert http.call_count == 0


def test_unknown_endpoint_rejected_before_request() -> None:
    with requests_mock.Mocker() as http:
        with pytest.raises(UnknownResourceError):
            read_rows("../unknown", make_manager())
    assert http.call_count == 0


@pytest.mark.parametrize("exception_type", [ConnectionError, Timeout])
def test_credential_connection_error_hides_query_key(exception_type: type[RequestException]) -> None:
    with requests_mock.Mocker() as http:
        http.get(
            "https://app.ticketmaster.com/discovery/v2/events.json",
            exc=exception_type("Failed URL: https://app.ticketmaster.com/?apikey=fake-ticketmaster-key"),
        )
        with pytest.raises(RequestException, match="Ticketmaster connection failed") as error:
            validate_credentials(make_config(), "events", "v2")
    assert "fake-ticketmaster-key" not in str(error.value)
    assert error.value.__suppress_context__
