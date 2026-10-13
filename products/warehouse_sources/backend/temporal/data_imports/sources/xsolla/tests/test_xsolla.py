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
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.xsolla import XsollaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.xsolla.settings import AUTH_ERROR
from products.warehouse_sources.backend.temporal.data_imports.sources.xsolla.source import XsollaSource
from products.warehouse_sources.backend.temporal.data_imports.sources.xsolla.xsolla import (
    MERCHANT_ID_ERROR,
    XsollaResumeConfig,
    validate_credentials,
)


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


@pytest.mark.parametrize(
    "merchant_id,status,expected",
    [
        ("123", 200, (True, None)),
        ("123", 401, (False, AUTH_ERROR)),
        ("123", 403, (False, AUTH_ERROR)),
        ("123", 500, (False, "Xsolla returned an unexpected response (HTTP 500). Try again later.")),
        ("123.evil.example", 200, (False, MERCHANT_ID_ERROR)),
    ],
)
def test_validate_credentials(merchant_id: str, status: int, expected: tuple[bool, str | None]) -> None:
    with scripted_network(always(ScriptedResponse(status=status, json=[]))):
        result = validate_credentials(XsollaSourceConfig(merchant_id=merchant_id, api_key="test-xsolla-key"), "v2")

    assert result == expected
