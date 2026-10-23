from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.xsolla import XsollaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.xsolla.settings import AUTH_ERROR
from products.warehouse_sources.backend.temporal.data_imports.sources.xsolla.source import XsollaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.xsolla.xsolla import XsollaResumeConfig


def transaction(transaction_id: int, created: str) -> dict[str, Any]:
    return {"transaction": {"id": transaction_id, "create_date": created, "status": "done"}, "user": {"id": "u1"}}


@pytest.fixture(autouse=True)
def fixed_clock() -> Iterator[None]:
    with time_machine.travel("2010-01-20T12:00:00Z", tick=False):
        yield


@pytest.fixture
def config() -> XsollaSourceConfig:
    return XsollaSourceConfig(merchant_id="123", api_key="test-xsolla-key")


@pytest.fixture
def driver(config: XsollaSourceConfig) -> SourceDriver:
    return SourceDriver(XsollaSource(), config)


def test_transactions_walk_every_window_and_page(driver: SourceDriver) -> None:
    first_window = [transaction(i, "2010-01-02T10:00:00+00:00") for i in range(100)]
    last_window = [transaction(500, "2010-01-19T10:00:00+00:00")]

    def page(request: RecordedRequest) -> ScriptedResponse:
        window = request.param("datetime_from") or ""
        offset = int(request.param("offset") or 0)
        if window.startswith("2010-01-01"):
            return ScriptedResponse(json=first_window[offset : offset + 100])
        if window.startswith("2010-01-15"):
            return ScriptedResponse(json=last_window[offset : offset + 100])
        return ScriptedResponse(json=[])

    result = driver.run("transactions", page)

    assert [row["id"] for row in result.rows] == [*range(100), 500]
    assert result.rows[-1]["create_date"] == "2010-01-19T10:00:00+00:00"
    assert [(r.param("datetime_from"), r.param("datetime_to"), r.param("offset")) for r in result.requests] == [
        ("2010-01-01T00:00:00Z", "2010-01-07T23:59:59Z", "0"),
        ("2010-01-01T00:00:00Z", "2010-01-07T23:59:59Z", "100"),
        ("2010-01-08T00:00:00Z", "2010-01-14T23:59:59Z", "0"),
        ("2010-01-15T00:00:00Z", "2010-01-20T23:59:59Z", "0"),
    ]
    assert result.requests[0].headers["authorization"].startswith("Basic ")


@pytest.mark.parametrize(
    "use_incremental,watermark,expected_start",
    [
        (False, None, "2010-01-01T00:00:00Z"),
        (True, None, "2010-01-01T00:00:00Z"),
        (True, datetime(2010, 1, 18, 9, tzinfo=UTC), "2010-01-11T00:00:00Z"),
        (True, "2010-01-18T09:00:00Z", "2010-01-11T00:00:00Z"),
    ],
)
def test_transactions_start_window(
    driver: SourceDriver,
    use_incremental: bool,
    watermark: Any,
    expected_start: str,
) -> None:
    result = driver.run(
        "transactions",
        always(ScriptedResponse(json=[])),
        should_use_incremental_field=use_incremental,
        db_incremental_field_last_value=watermark,
    )

    assert result.requests[0].param("datetime_from") == expected_start


def test_transactions_resume_from_saved_window_and_offset(driver: SourceDriver) -> None:
    result = driver.run(
        "transactions",
        always(ScriptedResponse(json=[])),
        resume_state=XsollaResumeConfig(window_start="2010-01-08", offset=200),
    )

    first = result.requests[0]
    assert (first.param("datetime_from"), first.param("offset")) == ("2010-01-08T00:00:00Z", "200")
    assert result.saved_states[-1] == XsollaResumeConfig(window_start="2010-01-21")


def test_project_tables_read_each_project_and_resume_after_finished_projects(driver: SourceDriver) -> None:
    result = driver.run(
        "subscription_products",
        route(
            {
                "/merchants/123/projects": [ScriptedResponse(json=[{"id": 30}, {"id": 10}, {"id": 20}])],
                "/projects/20/subscriptions/products": [ScriptedResponse(json=[{"id": 1, "name": "VIP"}])],
                "/projects/30/subscriptions/products": [ScriptedResponse(json=[{"id": 1, "name": "Pass"}])],
            }
        ),
        resume_state=XsollaResumeConfig(project_id=20),
    )

    assert [(row["project_id"], row["id"], row["name"]) for row in result.rows] == [(20, 1, "VIP"), (30, 1, "Pass")]
    assert result.response is not None
    assert result.response.primary_keys == ["project_id", "id"]
    assert not any("/projects/10/" in url for url in result.urls)
    assert result.saved_states[-1] == XsollaResumeConfig(project_id=31)


@pytest.mark.parametrize(
    "table,path",
    [
        ("virtual_items", "admin/items/virtual_items"),
        ("virtual_currencies", "admin/items/virtual_currency"),
        ("bundles", "admin/items/bundle"),
    ],
)
def test_store_tables_page_each_project_and_skip_projects_without_a_store(
    driver: SourceDriver, table: str, path: str
) -> None:
    items = [{"sku": f"sku-{i}", "type": "virtual_good"} for i in range(51)]

    def store_page(request: RecordedRequest) -> ScriptedResponse:
        if request.path.endswith("/merchants/123/projects"):
            return ScriptedResponse(json=[{"id": 20}, {"id": 10}])
        if "/project/10/" in request.path:
            return ScriptedResponse(status=404, json={"errorCode": 4001, "errorMessage": "Project not found"})
        offset = int(request.param("offset") or 0)
        return ScriptedResponse(
            json={
                "has_more": offset + 50 < len(items),
                "total_items_count": len(items),
                "items": items[offset : offset + 50],
            }
        )

    result = driver.run(table, store_page)

    assert result.raised is None
    assert [(row["project_id"], row["sku"]) for row in result.rows] == [(20, f"sku-{i}") for i in range(51)]
    assert [request.url.split("?")[0] for request in result.requests[1:]] == [
        f"https://store.xsolla.com/api/v2/project/10/{path}",
        f"https://store.xsolla.com/api/v2/project/20/{path}",
        f"https://store.xsolla.com/api/v2/project/20/{path}",
    ]
    assert [(r.param("offset"), r.param("limit")) for r in result.requests[2:]] == [("0", "50"), ("50", "50")]
    assert result.response is not None
    assert result.response.primary_keys == ["project_id", "sku"]


def test_transaction_registry_reads_v3_in_92_day_windows_and_pages(driver: SourceDriver) -> None:
    rows = [
        {"transaction": {"id": i, "status": "done"}, "payment_details": {"payout": {"amount": 1.5}}} for i in range(101)
    ]

    def registry_page(request: RecordedRequest) -> ScriptedResponse:
        if request.param("datetime_from") != "2010-01-01":
            return ScriptedResponse(json=[])
        offset = int(request.param("offset") or 0)
        return ScriptedResponse(json=rows[offset : offset + 100])

    with time_machine.travel("2010-06-01T12:00:00Z", tick=False):
        result = driver.run("transaction_registry", registry_page)

    assert [row["id"] for row in result.rows] == list(range(101))
    assert {request.url.split("?")[0] for request in result.requests} == {
        "https://api.xsolla.com/merchant/v3/merchants/123/reports/transactions/registry.json"
    }
    assert [
        (r.param("datetime_from"), r.param("datetime_to"), r.param("offset"), r.param("in_transfer_currency"))
        for r in result.requests
    ] == [
        ("2010-01-01", "2010-04-02", "0", "0"),
        ("2010-01-01", "2010-04-02", "100", "0"),
        ("2010-04-03", "2010-06-01", "0", "0"),
    ]


def test_report_windows_drop_rows_already_seen_in_an_earlier_window(driver: SourceDriver) -> None:
    with time_machine.travel("2010-06-01T12:00:00Z", tick=False):
        result = driver.run(
            "payouts",
            always(ScriptedResponse(json=[{"payout": {"id": 7, "date": "2010-03-31T00:00:00+00:00"}, "canceled": 0}])),
        )

    assert len(result.requests) == 2
    assert [row["id"] for row in result.rows] == [7]


def test_sync_raises_actionable_error_on_rejected_credentials(driver: SourceDriver) -> None:
    result = driver.run("promotions", [ScriptedResponse(status=401, json={"message": "Unauthorized"})])

    assert isinstance(result.raised, Exception)
    assert AUTH_ERROR in str(result.raised)
