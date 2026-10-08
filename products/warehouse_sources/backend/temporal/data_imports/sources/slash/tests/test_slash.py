from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock

import requests_mock
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.slash import SlashSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.slash.slash import (
    SlashResumeConfig,
    slash_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.slash.source import SlashSource


@pytest.fixture
def http() -> Iterator[requests_mock.Mocker]:
    with requests_mock.Mocker() as mock:
        yield mock


@pytest.fixture
def manager() -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = False
    return manager


@pytest.mark.parametrize(
    ("endpoint", "path", "row"),
    [
        ("accounts", "account", {"id": "account-example"}),
        ("transactions", "transaction", {"id": "transaction-example", "date": "2026-01-02T00:00:00Z"}),
        ("cards", "card", {"id": "card-example"}),
        ("invoices", "invoice", {"invoice": {"id": "invoice-example"}, "invoiceDetails": {"memo": "Example"}}),
        ("invoice_series", "invoice-series", {"id": "series-example"}),
        ("expense_reports", "expense-report", {"id": "expense-example"}),
        ("contacts", "contact", {"id": "contact-example"}),
    ],
)
@pytest.mark.parametrize("legal_entity_id", [None, "entity-example"])
def test_requests_and_row_identity(
    http: requests_mock.Mocker,
    manager: MagicMock,
    endpoint: str,
    path: str,
    row: dict[str, Any],
    legal_entity_id: str | None,
) -> None:
    http.get(f"https://api.slash.com/{path}", json={"items": [row], "metadata": {"count": 1}})
    response = slash_source(
        SlashSourceConfig(api_key="fake-key", legal_entity_id=legal_entity_id),
        endpoint,
        1,
        "job-example",
        manager,
        False,
        "2026-01-01T00:00:00Z",
    )
    rows = [item for page in cast(Iterable[Any], response.items()) for item in page]
    expected = {**row, "id": row["invoice"]["id"]} if endpoint == "invoices" else row
    assert rows == [expected]
    assert len(http.request_history) == 1
    request = http.request_history[0]
    assert request.headers["X-API-Key"] == "fake-key"
    assert request.headers.get("x-legal-entity") == legal_entity_id
    assert request.qs == {}
    manager.save_state.assert_not_called()


@pytest.mark.parametrize("terminal", [{}, {"nextCursor": None}, {"nextCursor": ""}])
@pytest.mark.parametrize("resumed", [False, True])
def test_cursor_pages_and_checkpoints(
    http: requests_mock.Mocker, manager: MagicMock, terminal: dict[str, Any], resumed: bool
) -> None:
    manager.can_resume.return_value = resumed
    manager.load_state.return_value = SlashResumeConfig(cursor="saved-cursor")
    http.get(
        "https://api.slash.com/transaction",
        [
            {"json": {"items": [{"id": "first"}], "metadata": {"nextCursor": "next-cursor"}}},
            {"json": {"items": [], "metadata": {"nextCursor": "last-cursor"}}},
            {"json": {"items": [{"id": "last"}], "metadata": terminal}},
        ],
    )
    response = slash_source(
        SlashSourceConfig(api_key="fake-key"),
        "transactions",
        1,
        "job-example",
        manager,
        True,
        "2026-01-01T00:00:00Z",
    )
    iterator = iter(cast(Iterable[Any], response.items()))
    assert next(iterator) == [{"id": "first"}]
    assert list(iterator) == [[{"id": "last"}]]
    assert [call.args[0].cursor for call in manager.save_state.call_args_list] == ["next-cursor", "last-cursor"]
    assert [request.qs.get("cursor") for request in http.request_history] == [
        ["saved-cursor"] if resumed else None,
        ["next-cursor"],
        ["last-cursor"],
    ]
    assert all(request.qs["filter:from_date"] == ["1767225600000"] for request in http.request_history)
    assert response.sort_mode == "desc"


@pytest.mark.parametrize(
    ("incremental", "watermark", "expected"),
    [
        (True, None, {}),
        (False, "2026-01-01T00:00:00Z", {}),
        (True, "2026-01-01T00:00:00Z", {"filter:from_date": ["1767225600000"]}),
        (True, datetime(2026, 1, 1, tzinfo=UTC), {"filter:from_date": ["1767225600000"]}),
        (True, datetime(2026, 1, 1), {"filter:from_date": ["1767225600000"]}),
        (True, "2026-01-01T01:00:00+01:00", {"filter:from_date": ["1767225600000"]}),
    ],
)
def test_transaction_time_filter(
    http: requests_mock.Mocker,
    manager: MagicMock,
    incremental: bool,
    watermark: str | datetime | None,
    expected: dict[str, list[str]],
) -> None:
    http.get("https://api.slash.com/transaction", json={"items": [], "metadata": {}})
    response = slash_source(
        SlashSourceConfig(api_key="fake-key"), "transactions", 1, "job-example", manager, incremental, watermark
    )
    assert list(cast(Iterable[Any], response.items())) == []
    assert http.request_history[0].qs == expected


def test_repeated_cursor_fails(http: requests_mock.Mocker, manager: MagicMock) -> None:
    http.get("https://api.slash.com/card", json={"items": [{"id": "example"}], "metadata": {"nextCursor": "same"}})
    response = slash_source(SlashSourceConfig(api_key="fake-key"), "cards", 1, "job-example", manager, False, None)
    with pytest.raises(ValueError, match="not advancing"):
        list(cast(Iterable[Any], response.items()))
    assert len(http.request_history) == 2


@pytest.mark.parametrize(
    ("status", "schema", "expected", "message"),
    [
        (200, None, True, None),
        (200, "cards", True, None),
        (401, None, False, "Slash rejected the API key. Check the key in your Slash dashboard."),
        (403, None, True, None),
        (
            403,
            "cards",
            False,
            "Your Slash key cannot access this resource. Check its permissions and the legal entity ID.",
        ),
        (400, None, False, "Slash rejected the request. User-scoped keys require a valid legal entity ID."),
    ],
)
def test_credential_probe(
    http: requests_mock.Mocker, status: int, schema: str | None, expected: bool, message: str | None
) -> None:
    path = "card" if schema else "account"
    http.get(
        f"https://api.slash.com/{path}", status_code=status, json={"items": [], "metadata": {"nextCursor": "unused"}}
    )
    assert validate_credentials(SlashSourceConfig(api_key="fake-key", legal_entity_id="entity-example"), schema) == (
        expected,
        message,
    )
    assert len(http.request_history) == 1
    assert http.request_history[0].headers["X-API-Key"] == "fake-key"
    assert http.request_history[0].headers["x-legal-entity"] == "entity-example"


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_sync_error_mapping(http: requests_mock.Mocker, manager: MagicMock, status: int) -> None:
    http.get("https://api.slash.com/card", status_code=status, json={"success": False, "rawStatus": status})
    response = slash_source(SlashSourceConfig(api_key="fake-key"), "cards", 1, "job-example", manager, False, None)
    with pytest.raises(HTTPError) as error:
        list(cast(Iterable[Any], response.items()))
    matches = [
        message for pattern, message in SlashSource().get_non_retryable_errors().items() if pattern in str(error.value)
    ]
    assert bool(matches) == (status != 404)
    assert len(http.request_history) == 1


def test_unknown_endpoint(manager: MagicMock) -> None:
    with pytest.raises(UnknownResourceError):
        slash_source(SlashSourceConfig(api_key="fake-key"), "unknown", 1, "job-example", manager, False, None)


def test_probe_unexpected_error_propagates(http: requests_mock.Mocker) -> None:
    http.get("https://api.slash.com/account", status_code=404, json={"success": False})
    with pytest.raises(HTTPError):
        validate_credentials(SlashSourceConfig(api_key="fake-key"), None)
