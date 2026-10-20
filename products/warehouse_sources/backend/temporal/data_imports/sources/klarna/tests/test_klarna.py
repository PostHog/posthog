from base64 import b64encode
from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.klarna import KlarnaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.klarna.klarna import KlarnaResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.klarna.source import KlarnaSource


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
