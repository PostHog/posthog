from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine
from unittest.mock import MagicMock, patch

import requests_mock
from requests import Session

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.xsolla import XsollaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.xsolla.settings import AUTH_ERROR
from products.warehouse_sources.backend.temporal.data_imports.sources.xsolla.xsolla import (
    MERCHANT_ID_ERROR,
    XsollaResumeConfig,
    validate_credentials,
    xsolla_source,
)

BASE = "https://api.xsolla.com/merchant/v2"
SEARCH_URL = f"{BASE}/merchants/123/reports/transactions/search.json"


def rows_of(response: SourceResponse) -> list[dict[str, Any]]:
    items = response.items()
    assert isinstance(items, Iterable)
    return [row for page in items for row in page]


def transaction(transaction_id: int, created: str) -> dict[str, Any]:
    return {"transaction": {"id": transaction_id, "create_date": created, "status": "done"}, "user": {"id": "u1"}}


@pytest.fixture(autouse=True)
def fixed_clock() -> Iterator[None]:
    with time_machine.travel("2010-01-20T12:00:00Z", tick=False):
        yield


@pytest.fixture
def http() -> Iterator[requests_mock.Mocker]:
    with (
        requests_mock.Mocker() as mock,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session",
            side_effect=lambda **kwargs: Session(),
        ),
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.xsolla.xsolla.make_tracked_session",
            side_effect=lambda **kwargs: Session(),
        ),
    ):
        yield mock


@pytest.fixture
def config() -> XsollaSourceConfig:
    return XsollaSourceConfig(merchant_id="123", api_key="test-xsolla-key")


@pytest.fixture
def manager() -> MagicMock:
    mock = MagicMock(spec=ResumableSourceManager)
    mock.can_resume.return_value = False
    return mock


def test_transactions_walk_every_window_and_page(
    http: requests_mock.Mocker, config: XsollaSourceConfig, manager: MagicMock
) -> None:
    first_window = [transaction(i, "2010-01-02T10:00:00+00:00") for i in range(100)]
    last_window = [transaction(500, "2010-01-19T10:00:00+00:00")]

    def page(request: Any, context: Any) -> list[dict[str, Any]]:
        window = request.qs["datetime_from"][0]
        offset = int(request.qs["offset"][0])
        if window.startswith("2010-01-01"):
            return first_window[offset : offset + 100]
        if window.startswith("2010-01-15"):
            return last_window[offset : offset + 100]
        return []

    http.get(SEARCH_URL, json=page)
    rows = rows_of(xsolla_source(config, "transactions", 1, "job", manager, "v2"))

    assert [row["id"] for row in rows] == [*range(100), 500]
    assert rows[-1]["create_date"] == "2010-01-19T10:00:00+00:00"
    requested = [(r.qs["datetime_from"][0], r.qs["datetime_to"][0], r.qs["offset"][0]) for r in http.request_history]
    assert requested == [
        ("2010-01-01t00:00:00z", "2010-01-07t23:59:59z", "0"),
        ("2010-01-01t00:00:00z", "2010-01-07t23:59:59z", "100"),
        ("2010-01-08t00:00:00z", "2010-01-14t23:59:59z", "0"),
        ("2010-01-15t00:00:00z", "2010-01-20t23:59:59z", "0"),
    ]
    assert http.request_history[0].headers["Authorization"].startswith("Basic ")


@pytest.mark.parametrize(
    "use_incremental,watermark,expected_start",
    [
        (False, None, "2010-01-01t00:00:00z"),
        (True, None, "2010-01-01t00:00:00z"),
        (True, datetime(2010, 1, 18, 9, tzinfo=UTC), "2010-01-11t00:00:00z"),
        (True, "2010-01-18T09:00:00Z", "2010-01-11t00:00:00z"),
    ],
)
def test_transactions_start_window(
    http: requests_mock.Mocker,
    config: XsollaSourceConfig,
    manager: MagicMock,
    use_incremental: bool,
    watermark: Any,
    expected_start: str,
) -> None:
    http.get(SEARCH_URL, json=[])

    rows_of(
        xsolla_source(
            config,
            "transactions",
            1,
            "job",
            manager,
            "v2",
            should_use_incremental_field=use_incremental,
            db_incremental_field_last_value=watermark,
        )
    )

    assert http.request_history[0].qs["datetime_from"][0] == expected_start


def test_transactions_resume_from_saved_window_and_offset(
    http: requests_mock.Mocker, config: XsollaSourceConfig, manager: MagicMock
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = XsollaResumeConfig(window_start="2010-01-08", offset=200)
    http.get(SEARCH_URL, json=[])

    rows_of(xsolla_source(config, "transactions", 1, "job", manager, "v2"))

    first = http.request_history[0]
    assert (first.qs["datetime_from"][0], first.qs["offset"][0]) == ("2010-01-08t00:00:00z", "200")
    assert manager.save_state.call_args_list[-1].args[0] == XsollaResumeConfig(window_start="2010-01-21")


def test_project_tables_read_each_project_and_resume_after_finished_projects(
    http: requests_mock.Mocker, config: XsollaSourceConfig, manager: MagicMock
) -> None:
    manager.can_resume.return_value = True
    manager.load_state.return_value = XsollaResumeConfig(project_id=20)
    http.get(f"{BASE}/merchants/123/projects", json=[{"id": 30}, {"id": 10}, {"id": 20}])
    http.get(f"{BASE}/projects/20/subscriptions/products", json=[{"id": 1, "name": "VIP"}])
    http.get(f"{BASE}/projects/30/subscriptions/products", json=[{"id": 1, "name": "Pass"}])

    response = xsolla_source(config, "subscription_products", 1, "job", manager, "v2")
    rows = rows_of(response)

    assert [(row["project_id"], row["id"], row["name"]) for row in rows] == [(20, 1, "VIP"), (30, 1, "Pass")]
    assert response.primary_keys == ["project_id", "id"]
    assert not any("/projects/10/" in request.url for request in http.request_history)
    assert manager.save_state.call_args_list[-1].args[0] == XsollaResumeConfig(project_id=31)


def test_report_windows_drop_rows_already_seen_in_an_earlier_window(
    http: requests_mock.Mocker, config: XsollaSourceConfig, manager: MagicMock
) -> None:
    with time_machine.travel("2010-06-01T12:00:00Z", tick=False):
        http.get(
            f"{BASE}/merchants/123/reports/transfers",
            json=[{"payout": {"id": 7, "date": "2010-03-31T00:00:00+00:00"}, "canceled": 0}],
        )
        rows = rows_of(xsolla_source(config, "payouts", 1, "job", manager, "v2"))

    assert len(http.request_history) == 2
    assert [row["id"] for row in rows] == [7]


def test_sync_raises_actionable_error_on_rejected_credentials(
    http: requests_mock.Mocker, config: XsollaSourceConfig, manager: MagicMock
) -> None:
    http.get(f"{BASE}/merchants/123/promotions", status_code=401, json={"message": "Unauthorized"})

    with pytest.raises(Exception, match=AUTH_ERROR):
        rows_of(xsolla_source(config, "promotions", 1, "job", manager, "v2"))


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
def test_validate_credentials(
    http: requests_mock.Mocker, merchant_id: str, status: int, expected: tuple[bool, str | None]
) -> None:
    http.get(f"{BASE}/merchants/123/projects", status_code=status, json=[])

    result = validate_credentials(XsollaSourceConfig(merchant_id=merchant_id, api_key="test-xsolla-key"), "v2")

    assert result == expected
