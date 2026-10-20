from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mono import MonoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mono.mono import (
    MonoResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mono.source import MonoSource

CONFIG = MonoSourceConfig(api_key="test_sk_fake_mono_key", start_date="2020-01-01")


def driver() -> SourceDriver:
    return SourceDriver(MonoSource(), CONFIG)


def page(rows: list[dict[str, Any]], next_url: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"status": "successful", "data": rows, "meta": {"next": next_url}})


@time_machine.travel("2026-06-15T12:00:00Z", tick=False)
@pytest.mark.parametrize(
    "incremental,watermark,expected_start",
    [
        (False, "2026-06-10T15:00:00Z", "01-01-2020"),
        (True, None, "01-01-2020"),
        (True, "2026-06-10T15:00:00Z", "09-06-2026"),
        (True, datetime(2026, 6, 10, 15, tzinfo=UTC), "09-06-2026"),
        (True, "2019-01-01T00:00:00Z", "01-01-2020"),
        (True, "2026-06-15T11:00:00Z", "14-06-2026"),
    ],
)
def test_transaction_filters_survive_pagination_and_fanout(
    incremental: bool, watermark: object, expected_start: str
) -> None:
    result = driver().run(
        "transactions",
        [
            page([{"id": "account-a"}], "https://api.withmono.com/v2/accounts?page=2"),
            page(
                [{"id": "shared-id", "date": "2026-06-10T00:00:00Z"}],
                "https://api.withmono.com/v2/account-a/transactions?page=2",
            ),
            page([{"id": "older-id", "date": "2026-06-09T00:00:00Z"}]),
            page([{"id": "account-b"}]),
            page([{"id": "shared-id", "date": "2026-06-11T00:00:00Z"}]),
        ],
        should_use_incremental_field=incremental,
        db_incremental_field_last_value=watermark,
    )

    assert result.raised is None
    assert [(row["account_id"], row["id"]) for row in result.rows] == [
        ("account-a", "shared-id"),
        ("account-a", "older-id"),
        ("account-b", "shared-id"),
    ]
    assert result.response is not None
    assert len({tuple(row[key] for key in result.response.primary_keys or []) for row in result.rows}) == 3
    assert result.response.sort_mode == "desc"
    assert len(result.requests) == 5
    for request in result.requests:
        assert request.headers["mono-sec-key"] == CONFIG.api_key
        assert "x-real-time" not in request.headers
        if "/transactions" in request.path:
            assert request.query == {
                "page": (request.param("page"),),
                "start": (expected_start,),
                "end": ("15-06-2026",),
                "paginate": ("true",),
                "limit": ("100",),
            }
    assert result.saved_states[0] == MonoResumeConfig(
        paginator_state={"completed": [], "current": "accounts/account-a/transactions", "child_state": {"page": 2}},
        start=expected_start,
        end="15-06-2026",
    )
    assert result.saved_states[-1].paginator_state == {
        "completed": ["accounts/account-a/transactions", "accounts/account-b/transactions"],
        "current": None,
        "child_state": None,
    }


@time_machine.travel("2026-06-16T12:00:00Z", tick=False)
def test_resumes_child_page_with_original_date_bounds_and_skips_completed_accounts() -> None:
    saved = MonoResumeConfig(
        paginator_state={
            "completed": ["accounts/account-a/transactions"],
            "current": "accounts/account-b/transactions",
            "child_state": {"page": 3},
        },
        start="09-06-2026",
        end="15-06-2026",
    )
    result = driver().run(
        "transactions",
        [page([{"id": "account-a"}, {"id": "account-b"}]), page([{"id": "transaction-3"}])],
        resume_state=saved,
    )

    assert result.raised is None
    assert result.rows == [{"id": "transaction-3", "account_id": "account-b"}]
    assert result.paths == ["/v2/accounts", "/v2/accounts/account-b/transactions"]
    assert result.requests[1].query == {
        "page": ("3",),
        "start": ("09-06-2026",),
        "end": ("15-06-2026",),
        "paginate": ("true",),
        "limit": ("100",),
    }


def payments_page(rows: list[dict[str, Any]], pages: int) -> ScriptedResponse:
    return ScriptedResponse(
        json={"status": "successful", "data": {"payments": rows}, "meta": {"paging": {"pages": pages, "next": None}}}
    )


@time_machine.travel("2026-06-15T12:00:00Z", tick=False)
@pytest.mark.parametrize(
    "endpoint,incremental,watermark,script,expected_path,expected_queries,expected_ids",
    [
        (
            "institutions",
            False,
            None,
            [page([{"id": "institution-1"}, {"id": "institution-2"}])],
            "/v3/institutions",
            [{}],
            ["institution-1", "institution-2"],
        ),
        (
            "mandates",
            False,
            None,
            [page([{"id": "mandate-1"}, {"id": "mandate-2"}]), page([{"id": "mandate-3"}]), page([])],
            "/v3/payments/mandates",
            [{"page": (str(number),), "limit": ("100",)} for number in (1, 2, 3)],
            ["mandate-1", "mandate-2", "mandate-3"],
        ),
        (
            "payments",
            False,
            "2026-06-10T15:00:00Z",
            [payments_page([{"id": "payment-1"}], 2), payments_page([{"id": "payment-2"}], 2)],
            "/v2/payments/transactions",
            [{"page": (str(number),), "limit": ("100",)} for number in (1, 2)],
            ["payment-1", "payment-2"],
        ),
        (
            "payments",
            True,
            None,
            [payments_page([{"id": "payment-1"}], 1)],
            "/v2/payments/transactions",
            [{"page": ("1",), "limit": ("100",)}],
            ["payment-1"],
        ),
        (
            "payments",
            True,
            "2026-06-10T15:00:00Z",
            [payments_page([{"id": "payment-1"}], 1)],
            "/v2/payments/transactions",
            [{"page": ("1",), "limit": ("100",), "start": ("09-06-2026",), "end": ("15-06-2026",)}],
            ["payment-1"],
        ),
        (
            "mandate_debits",
            False,
            None,
            [page([{"mandate": "mandate-1", "reference": "debit-1"}], "https://api.withmono.com/v3/x?page=2")],
            "/v3/payments/mandates/debits",
            [{}],
            ["debit-1"],
        ),
        (
            "mandate_debits",
            True,
            datetime(2026, 6, 10, 15, tzinfo=UTC),
            [page([{"mandate": "mandate-1", "reference": "debit-1"}])],
            "/v3/payments/mandates/debits",
            [{"start_date": ("2026-06-09",), "end_date": ("2026-06-15",)}],
            ["debit-1"],
        ),
    ],
)
def test_payment_and_coverage_tables_request_the_right_version_filters_and_pages(
    endpoint: str,
    incremental: bool,
    watermark: object,
    script: list[ScriptedResponse],
    expected_path: str,
    expected_queries: list[dict[str, tuple[str, ...]]],
    expected_ids: list[str],
) -> None:
    result = driver().run(
        endpoint, script, should_use_incremental_field=incremental, db_incremental_field_last_value=watermark
    )

    assert result.raised is None
    assert [row.get("reference", row.get("id")) for row in result.rows] == expected_ids
    assert result.paths == [expected_path] * len(expected_queries)
    assert result.queries == expected_queries
    assert all(request.headers["mono-sec-key"] == CONFIG.api_key for request in result.requests)


@pytest.mark.parametrize(
    "start,end,expected_query",
    [
        (None, None, {"page": ("3",), "limit": ("100",)}),
        (
            "09-06-2026",
            "15-06-2026",
            {"page": ("3",), "limit": ("100",), "start": ("09-06-2026",), "end": ("15-06-2026",)},
        ),
    ],
)
@time_machine.travel("2026-06-16T12:00:00Z", tick=False)
def test_resumed_payments_keep_the_saved_date_window(
    start: str | None, end: str | None, expected_query: dict[str, tuple[str, ...]]
) -> None:
    saved = MonoResumeConfig(paginator_state={"page": 3}, start=start, end=end)
    result = driver().run(
        "payments",
        [payments_page([{"id": "payment-5"}], 3)],
        resume_state=saved,
        should_use_incremental_field=start is not None,
        db_incremental_field_last_value="2026-06-15T00:00:00Z" if start else None,
    )

    assert result.raised is None
    assert [row["id"] for row in result.rows] == ["payment-5"]
    assert result.queries == [expected_query]


@pytest.mark.parametrize("next_url", ["?page=1", "?page=0", "?page=no", "?offset=2", "?page=2&page=3"])
def test_invalid_next_page_fails_instead_of_truncating_or_looping(next_url: str) -> None:
    result = driver().run("customers", [page([{"id": "customer-1"}], next_url)])

    assert isinstance(result.raised, ValueError)
    assert "invalid pagination link" in str(result.raised)
    assert len(result.requests) == 1


@pytest.mark.parametrize(
    "status,expected",
    [
        (200, None),
    ],
)
@time_machine.travel("2026-06-15T12:00:00Z", tick=False)
def test_credential_probe_maps_auth_errors_and_reads_only_one_page(status: int, expected: str | None) -> None:
    body = (
        page([], "https://api.withmono.com/v2/customers?page=2").json
        if status == 200
        else {"status": "failed", "message": "Unauthorized request.", "data": None}
    )
    with scripted_network([ScriptedResponse(status=status, json=body)]) as network:
        valid, error = validate_credentials(CONFIG, "v2", 1)

    assert valid is (status == 200)
    if expected:
        assert expected in (error or "")
    else:
        assert error is None
    assert len(network.requests_log) == 1
    assert network.requests_log[0].headers["mono-sec-key"] == CONFIG.api_key


@pytest.mark.parametrize("status", [400, 404])
def test_other_credential_probe_errors_propagate(status: int) -> None:
    with scripted_network([ScriptedResponse(status=status, json={"status": "failed"})]) as network:
        with pytest.raises(HTTPError):
            validate_credentials(CONFIG, "v2", 1)
    assert len(network.requests_log) == 1


@pytest.mark.parametrize("status,expected", [(401, "secret API key"), (403, "denied access")])
def test_sync_auth_errors_match_user_facing_error_mapping(status: int, expected: str) -> None:
    result = driver().run("accounts", [ScriptedResponse(status=status, json={"message": "Unauthorized request."})])

    assert isinstance(result.raised, HTTPError)
    messages = MonoSource().get_non_retryable_errors()
    assert any(pattern in str(result.raised) and expected in (message or "") for pattern, message in messages.items())
    assert len(result.requests) == 1


@pytest.mark.parametrize(
    "start_date,expected",
    [
        ("invalid", "YYYY-MM-DD"),
        ("2026-02-30", "YYYY-MM-DD"),
        ("20260101", "YYYY-MM-DD"),
        ("2026-06-15", "before today"),
        ("2026-06-16", "before today"),
    ],
)
@time_machine.travel("2026-06-15T12:00:00Z", tick=False)
def test_invalid_start_dates_fail_before_any_request(start_date: str, expected: str) -> None:
    with scripted_network([]) as network:
        valid, error = validate_credentials(MonoSourceConfig(api_key=CONFIG.api_key, start_date=start_date), "v2", 1)

    assert not valid
    assert expected in (error or "")
    assert network.requests_log == []


def test_invalid_watermark_and_unknown_table_fail_before_any_request() -> None:
    invalid_watermark = driver().run(
        "transactions",
        [],
        should_use_incremental_field=True,
        db_incremental_field_last_value="invalid",
    )
    unknown_table = driver().run("missing", [])

    assert isinstance(invalid_watermark.raised, ValueError)
    assert "invalid transactions watermark" in str(invalid_watermark.raised)
    assert isinstance(unknown_table.raised, UnknownResourceError)
    assert invalid_watermark.requests == []
    assert unknown_table.requests == []
