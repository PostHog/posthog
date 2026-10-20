from datetime import UTC, datetime
from typing import Any

import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.slash import SlashSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.slash.slash import (
    SlashResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.slash.source import SlashSource


def _run(endpoint: str, script: Script, legal_entity_id: str | None = None, **inputs: Any) -> DriveResult:
    config = SlashSourceConfig(api_key="fake-key", legal_entity_id=legal_entity_id)
    return SourceDriver(SlashSource(), config).run(endpoint, script, **inputs)


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
def test_requests_and_row_identity(endpoint: str, path: str, row: dict[str, Any], legal_entity_id: str | None) -> None:
    result = _run(
        endpoint,
        [ScriptedResponse(json={"items": [row], "metadata": {"count": 1}})],
        legal_entity_id,
        db_incremental_field_last_value="2026-01-01T00:00:00Z",
    )
    expected = {**row, "id": row["invoice"]["id"]} if endpoint == "invoices" else row
    assert result.rows == [expected]
    assert result.paths == [f"/{path}"]
    request = result.requests[0]
    assert request.headers["x-api-key"] == "fake-key"
    assert request.headers.get("x-legal-entity") == legal_entity_id
    assert request.query == {}
    assert result.saved_states == []


@pytest.mark.parametrize("terminal", [{}, {"nextCursor": None}, {"nextCursor": ""}])
@pytest.mark.parametrize("resumed", [False, True])
def test_cursor_pages_and_checkpoints(terminal: dict[str, Any], resumed: bool) -> None:
    result = _run(
        "transactions",
        [
            ScriptedResponse(json={"items": [{"id": "first"}], "metadata": {"nextCursor": "next-cursor"}}),
            ScriptedResponse(json={"items": [], "metadata": {"nextCursor": "last-cursor"}}),
            ScriptedResponse(json={"items": [{"id": "last"}], "metadata": terminal}),
        ],
        should_use_incremental_field=True,
        db_incremental_field_last_value="2026-01-01T00:00:00Z",
        resume_state=SlashResumeConfig(cursor="saved-cursor") if resumed else None,
    )
    assert result.items == [[{"id": "first"}], [{"id": "last"}]]
    assert result.saved_states == [SlashResumeConfig(cursor="next-cursor"), SlashResumeConfig(cursor="last-cursor")]
    assert result.params("cursor") == ["saved-cursor" if resumed else None, "next-cursor", "last-cursor"]
    assert result.params("filter:from_date") == ["1767225600000"] * 3
    assert result.response is not None
    assert result.response.sort_mode == "desc"


@pytest.mark.parametrize(
    ("incremental", "watermark", "expected"),
    [
        (True, None, {}),
        (False, "2026-01-01T00:00:00Z", {}),
        (True, "2026-01-01T00:00:00Z", {"filter:from_date": ("1767225600000",)}),
        (True, datetime(2026, 1, 1, tzinfo=UTC), {"filter:from_date": ("1767225600000",)}),
        (True, datetime(2026, 1, 1), {"filter:from_date": ("1767225600000",)}),
        (True, "2026-01-01T01:00:00+01:00", {"filter:from_date": ("1767225600000",)}),
    ],
)
def test_transaction_time_filter(
    incremental: bool,
    watermark: str | datetime | None,
    expected: dict[str, tuple[str, ...]],
) -> None:
    result = _run(
        "transactions",
        [ScriptedResponse(json={"items": [], "metadata": {}})],
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )
    assert result.rows == []
    assert result.queries[0] == expected


def test_repeated_cursor_fails() -> None:
    result = _run(
        "cards",
        always(ScriptedResponse(json={"items": [{"id": "example"}], "metadata": {"nextCursor": "same"}})),
    )
    assert isinstance(result.raised, ValueError)
    assert "not advancing" in str(result.raised)
    assert len(result.requests) == 2


@pytest.mark.parametrize(
    ("status", "schema", "expected", "message"),
    [
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
def test_credential_probe(status: int, schema: str | None, expected: bool, message: str | None) -> None:
    path = "/card" if schema else "/account"
    script = [ScriptedResponse(status=status, json={"items": [], "metadata": {"nextCursor": "unused"}})]
    with scripted_network(script) as network:
        outcome = validate_credentials(SlashSourceConfig(api_key="fake-key", legal_entity_id="entity-example"), schema)
    assert outcome == (expected, message)
    assert [request.path for request in network.requests_log] == [path]
    assert network.requests_log[0].headers["x-api-key"] == "fake-key"
    assert network.requests_log[0].headers["x-legal-entity"] == "entity-example"


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_sync_error_mapping(status: int) -> None:
    result = _run("cards", [ScriptedResponse(status=status, json={"success": False, "rawStatus": status})])
    assert isinstance(result.raised, HTTPError)
    matches = [
        message
        for pattern, message in SlashSource().get_non_retryable_errors().items()
        if pattern in str(result.raised)
    ]
    assert bool(matches) == (status != 404)
    assert len(result.requests) == 1


def test_probe_unexpected_error_propagates() -> None:
    with scripted_network([ScriptedResponse(status=404, json={"success": False})]):
        with pytest.raises(HTTPError):
            validate_credentials(SlashSourceConfig(api_key="fake-key"), None)
