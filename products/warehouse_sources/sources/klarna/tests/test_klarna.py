from base64 import b64encode
from datetime import UTC, datetime
from typing import Any

import pytest

from products.warehouse_sources.sources.klarna._config import KlarnaSourceConfig
from products.warehouse_sources.sources.klarna.klarna import KlarnaResumeConfig
from products.warehouse_sources.sources.klarna.source import KlarnaSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver


def driver(**config: Any) -> SourceDriver:
    return SourceDriver(KlarnaSource(), KlarnaSourceConfig(api_key="klarna_test_api_fake", **config))


@pytest.mark.parametrize("endpoint", ["payouts", "transactions"])
@pytest.mark.parametrize("include_total", [False, True])
def test_collection_pages_preserve_rows_and_commit_offsets(endpoint: str, include_total: bool) -> None:
    rows = [
        {
            "payment_reference": f"fake-payout-{index}",
            "capture_id": "",
            "type": "FEE",
            "amount": 25,
            "capture_date": "2024-01-01T00:00:00Z",
            "payout_date": "2024-01-02T00:00:00Z",
        }
        for index in range(1000)
    ]
    pagination = {"count": 500, "total": 1000} if include_total else {"count": 500}
    pages = [
        ScriptedResponse(json={endpoint: rows[:500], "pagination": pagination}),
        ScriptedResponse(json={endpoint: rows[500:], "pagination": pagination}),
    ]
    if not include_total:
        pages.append(ScriptedResponse(json={endpoint: [], "pagination": {"count": 0}}))
    result = driver().run(endpoint, pages)

    assert result.raised is None
    assert result.rows == rows
    assert result.paths == [f"/settlements/v1/{endpoint}"] * len(pages)
    assert result.params("offset") == (["0", "500"] if include_total else ["0", "500", "1000"])
    assert result.params("size") == ["500"] * len(pages)
    assert result.saved_states == (
        [KlarnaResumeConfig(offset=500)]
        if include_total
        else [KlarnaResumeConfig(offset=500), KlarnaResumeConfig(offset=1000)]
    )
    assert result.committed_states == result.saved_states
    assert all(request.param("start_date") is None for request in result.requests)
    assert all(request.param("order_id") is None for request in result.requests)


@pytest.mark.parametrize("endpoint", ["payouts", "transactions"])
def test_resume_fetches_only_the_remaining_page(endpoint: str) -> None:
    row = {"payment_reference": "fake-last-payout", "capture_date": "2024-01-01T00:00:00Z"}
    result = driver().run(
        endpoint,
        [ScriptedResponse(json={endpoint: [row], "pagination": {"count": 1, "total": 1001}})],
        resume_state=KlarnaResumeConfig(offset=1000),
    )

    assert result.raised is None
    assert result.rows == [row]
    assert result.params("offset") == ["1000"]
    assert result.saved_states == []


@pytest.mark.parametrize(
    ("region", "environment", "username", "host"),
    [
        ("eu", "live", None, "api.klarna.com"),
        ("na", "live", "fake-username", "api-na.klarna.com"),
        ("oc", "live", None, "api-oc.klarna.com"),
        ("eu", "playground", "fake-username", "api.playground.klarna.com"),
        ("na", "playground", None, "api-na.playground.klarna.com"),
        ("oc", "playground", "fake-username", "api-oc.playground.klarna.com"),
    ],
)
def test_requests_use_the_account_host_and_credential_format(
    region: str, environment: str, username: str | None, host: str
) -> None:
    result = driver(region=region, environment=environment, username=username).run(
        "payouts", [ScriptedResponse(json={"payouts": [], "pagination": {"count": 0}})]
    )

    assert result.raised is None
    assert result.urls == [f"https://{host}/settlements/v1/payouts?offset=0&size=500"]
    token = b64encode(f"{username}:klarna_test_api_fake".encode()).decode() if username else "klarna_test_api_fake"
    assert result.requests[0].headers["authorization"] == f"Basic {token}"
    assert result.requests[0].headers["accept"] == "application/json"


def test_transactions_keep_repeated_entries_without_a_merge_key() -> None:
    row = {"amount": 25, "capture_id": "", "order_id": "fake-order", "type": "FEE", "refund_id": None}
    result = driver().run(
        "transactions", [ScriptedResponse(json={"transactions": [row, row], "pagination": {"count": 2}})]
    )

    assert result.raised is None
    assert result.rows == [row, row]
    assert result.response is not None
    assert result.response.primary_keys is None


@pytest.mark.parametrize("endpoint", ["payouts", "transactions"])
def test_unexpected_response_cannot_replace_a_table_with_empty_rows(endpoint: str) -> None:
    result = driver().run(endpoint, [ScriptedResponse(json={"message": "Unexpected response"})])

    assert result.raised is not None
    assert result.rows == []


def dispute(index: int) -> dict[str, Any]:
    return {
        "payment_dispute_id": f"krn:network:eu1:test:payment:dispute:fake-{index}",
        "state": "INITIATED",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-02T00:00:00Z",
    }


def dispute_page(rows: list[dict[str, Any]], last_item: str | None) -> ScriptedResponse:
    return ScriptedResponse(json={"disputes": rows, "pagination": {"count": len(rows), "last_item": last_item}})


@pytest.mark.parametrize(
    ("resume_state", "expected_cursors"),
    [
        (None, [None, "fake-cursor-1", "fake-cursor-2"]),
        (KlarnaResumeConfig(starting_after="fake-cursor-1"), ["fake-cursor-1", "fake-cursor-2"]),
    ],
)
def test_disputes_follow_the_cursor_until_it_is_null(
    resume_state: KlarnaResumeConfig | None, expected_cursors: list[str | None]
) -> None:
    pages = [
        dispute_page([dispute(0)], "fake-cursor-1"),
        dispute_page([dispute(1)], "fake-cursor-2"),
        dispute_page([], None),
    ][-len(expected_cursors) :]
    result = driver().run("disputes", pages, resume_state=resume_state)

    assert result.raised is None
    assert result.rows == [row for page in pages for row in page.json["disputes"]]
    assert result.paths == ["/v4/payment/disputes"] * len(pages)
    assert result.params("starting_after") == expected_cursors
    assert result.params("sort_by") == ["created_at"] * len(pages)
    assert result.params("offset") == [None] * len(pages)
    assert result.saved_states == [KlarnaResumeConfig(starting_after=cursor) for cursor in expected_cursors[1:]]


def test_disputes_stop_when_the_cursor_repeats() -> None:
    result = driver().run(
        "disputes",
        [dispute_page([dispute(0)], "fake-cursor-1"), dispute_page([dispute(1)], "fake-cursor-1")],
    )

    assert isinstance(result.raised, ValueError)


@pytest.mark.parametrize(
    ("incremental_field", "last_value", "expected_filters"),
    [
        (None, None, {"updated_at_start": None, "created_at_start": None}),
        ("updated_at", None, {"updated_at_start": None, "created_at_start": None}),
        (
            "updated_at",
            datetime(2025, 3, 4, 5, 6, 7, 890000, tzinfo=UTC),
            {"updated_at_start": "2025-03-04T05:06:07Z", "created_at_start": None},
        ),
        (
            "created_at",
            "2025-03-04T05:06:07+00:00",
            {"updated_at_start": None, "created_at_start": "2025-03-04T05:06:07Z"},
        ),
    ],
)
def test_incremental_disputes_filter_on_the_selected_field(
    incremental_field: str | None, last_value: Any, expected_filters: dict[str, str | None]
) -> None:
    result = driver().run(
        "disputes",
        [dispute_page([dispute(0)], None)],
        incremental_field=incremental_field,
        db_incremental_field_last_value=last_value,
    )

    assert result.raised is None
    assert result.rows == [dispute(0)]
    assert {name: result.params(name)[0] for name in expected_filters} == expected_filters
    assert result.response is not None
    assert result.response.sort_mode is None
