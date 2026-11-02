from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import time_machine
from unittest import mock

from parameterized import parameterized
from requests import Request

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.wasabi import WasabiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.settings import (
    DEFAULT_UTILIZATION_START_DATE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.source import WasabiSource
from products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.wasabi import (
    WasabiDateWindowPaginator,
    WasabiResumeConfig,
    _start_date,
    wasabi_source,
)

TODAY = date(2026, 7, 21)


class _FixedTodayPaginator(WasabiDateWindowPaginator):
    # Pin "today" so window math is deterministic in tests.
    @staticmethod
    def _today() -> date:
        return TODAY


def _fixed_today_paginator(start: date, window_days: int = 30) -> WasabiDateWindowPaginator:
    return _FixedTodayPaginator(start_date=start, window_days=window_days)


def _driver() -> SourceDriver:
    return SourceDriver(WasabiSource(), WasabiSourceConfig(api_key="key"))


class _FakeResumableSourceManager:
    def __init__(self, state: WasabiResumeConfig | None = None) -> None:
        self._state = state
        self.saved: list[WasabiResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> WasabiResumeConfig | None:
        return self._state

    def save_state(self, state: WasabiResumeConfig) -> None:
        self.saved.append(state)


class TestWasabiDateWindowPaginator:
    def test_terminates_once_window_reaches_today(self) -> None:
        paginator = _fixed_today_paginator(TODAY)
        request = Request(method="GET", url="x", params={})
        paginator.init_request(request)
        assert request.params == {"from": "2026-07-21", "to": "2026-07-21"}
        paginator.update_state(mock.Mock())
        assert paginator.has_next_page is False
        assert paginator.get_resume_state() is None

    def test_resume_state_points_at_next_window(self) -> None:
        paginator = _fixed_today_paginator(date(2024, 1, 1))
        request = Request(method="GET", url="x", params={})
        paginator.init_request(request)
        paginator.update_state(mock.Mock())
        paginator.update_request(request)
        assert paginator.get_resume_state() == {"next_from": "2024-01-31"}

    def test_future_start_date_is_clamped_to_today(self) -> None:
        paginator = _fixed_today_paginator(date(2024, 1, 1))
        paginator.set_resume_state({"next_from": "2027-01-01"})
        request = Request(method="GET", url="x", params={})
        paginator.init_request(request)
        assert request.params == {"from": "2026-07-21", "to": "2026-07-21"}


class TestStartDate:
    @parameterized.expand(
        [
            ("iso_string", True, "2024-03-05T00:00:00Z", date(2024, 3, 5)),
            ("datetime", True, datetime(2024, 3, 5, 12, 30, tzinfo=UTC), date(2024, 3, 5)),
            ("date", True, date(2024, 3, 5), date(2024, 3, 5)),
            ("first_sync", True, None, date.fromisoformat(DEFAULT_UTILIZATION_START_DATE)),
            ("full_refresh", False, datetime(2024, 3, 5), date.fromisoformat(DEFAULT_UTILIZATION_START_DATE)),
            ("unparseable_string", True, "not-a-date", date.fromisoformat(DEFAULT_UTILIZATION_START_DATE)),
        ]
    )
    def test_start_date(self, _name: str, should_use_incremental: bool, last_value: Any, expected: date) -> None:
        assert _start_date(should_use_incremental, last_value) == expected


class TestWasabiSourceTransport:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.wasabi.rest_api_resource")
    def test_accounts_full_refresh(self, mock_rest_api_resource: mock.MagicMock) -> None:
        manager = _FakeResumableSourceManager()
        response = wasabi_source(
            api_key="key",
            endpoint="accounts",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=cast(Any, manager),
        )

        assert response.name == "accounts"
        assert response.primary_keys == ["AcctNum"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["CreateTime"]

        config = mock_rest_api_resource.call_args.args[0]
        resource = config["resources"][0]
        assert resource["write_disposition"] == "replace"
        assert resource["endpoint"]["path"] == "/v1/accounts"
        # WACA list endpoints return a bare JSON array.
        assert resource["endpoint"]["data_selector"] == "$"
        assert config["client"]["base_url"] == "https://partner.wasabisys.com"
        assert config["client"]["auth"] == {
            "type": "api_key",
            "name": "Authorization",
            "api_key": "key",
            "location": "header",
        }

    @parameterized.expand(
        [
            ("utilizations", ["UtilizationNum"], "/v1/utilizations"),
            ("bucket_utilizations", ["BucketUtilizationNum"], "/v1/utilizations/buckets"),
        ]
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.wasabi.rest_api_resource")
    def test_utilization_endpoints_incremental_merge(
        self,
        endpoint: str,
        expected_primary_keys: list[str],
        expected_path: str,
        mock_rest_api_resource: mock.MagicMock,
    ) -> None:
        manager = _FakeResumableSourceManager()
        response = wasabi_source(
            api_key="key",
            endpoint=endpoint,
            team_id=1,
            job_id="job-1",
            resumable_source_manager=cast(Any, manager),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 3, 5, tzinfo=UTC),
        )

        assert response.name == endpoint
        assert response.primary_keys == expected_primary_keys
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["StartTime"]
        assert response.sort_mode == "asc"

        config = mock_rest_api_resource.call_args.args[0]
        resource = config["resources"][0]
        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        assert resource["endpoint"]["path"] == expected_path
        paginator = resource["endpoint"]["paginator"]
        assert isinstance(paginator, WasabiDateWindowPaginator)
        # The window walk starts at the incremental watermark date.
        assert paginator._window_start == date(2024, 3, 5)

    def test_resume_state_is_seeded_into_paginator(self) -> None:
        result = _driver().run(
            "utilizations",
            always(ScriptedResponse(json=[])),
            resume_state=WasabiResumeConfig(paginator_state={"next_from": "2025-06-01"}),
        )

        assert result.params("from")[0] == "2025-06-01"

    def test_resume_hook_saves_state_after_batches(self) -> None:
        today = datetime.now(UTC).date()
        result = _driver().run(
            "utilizations",
            always(ScriptedResponse(json=[{"UtilizationNum": 1}])),
            incremental_field="StartTime",
            db_incremental_field_last_value=datetime.combine(today - timedelta(days=40), datetime.min.time(), UTC),
        )

        # Only mid-walk positions are saved: the final window completes the walk and saves nothing.
        assert result.saved_states == [
            WasabiResumeConfig(paginator_state={"next_from": (today - timedelta(days=10)).isoformat()})
        ]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.wasabi.wasabi.rest_api_resources")
    def test_sub_account_invoices_fans_out_from_accounts(self, mock_rest_api_resources: mock.MagicMock) -> None:
        parent = mock.Mock()
        parent.name = "accounts"
        child = mock.Mock()
        child.name = "sub_account_invoices"
        mock_rest_api_resources.return_value = [parent, child]
        manager = _FakeResumableSourceManager()

        response = wasabi_source(
            api_key="key",
            endpoint="sub_account_invoices",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=cast(Any, manager),
        )

        assert response.name == "sub_account_invoices"
        # Wasabi doesn't document SubInvoiceNum's uniqueness scope, so the parent
        # account number stays in the key to keep it unique table-wide.
        assert response.primary_keys == ["AcctNum", "SubInvoiceNum"]
        assert response.items() is child

        config = mock_rest_api_resources.call_args.args[0]
        parent_resource, child_resource = config["resources"]
        assert parent_resource["name"] == "accounts"
        assert child_resource["endpoint"]["path"] == "/v1/accounts/{acct_num}/invoices"
        assert child_resource["endpoint"]["params"]["acct_num"] == {
            "type": "resolve",
            "resource": "accounts",
            "field": "AcctNum",
        }
        assert child_resource["write_disposition"] == "replace"


_SUB_INVOICE_PARENT = {
    "AcctNum": 101,
    "InvoiceNum": 900,
    "CreateTime": "2026-02-01T00:00:00Z",
    "PeriodStart": "2026-01-01T00:00:00Z",
    "PeriodEnd": "2026-01-31T23:59:59Z",
}


def _sub_invoice_item(item_num: int, sub_invoice_num: int) -> dict[str, Any]:
    return {
        "SubInvoiceItemNum": item_num,
        "SubInvoiceNum": sub_invoice_num,
        "Type": "storage",
        "DisplayName": "Timed active storage",
        "Qty": 1.5,
        "UnitCost": 6.99,
        "Total": 10.49,
        "Currency": "USD",
    }


def _air_job(job_id: str) -> dict[str, Any]:
    return {
        "JobId": job_id,
        "AcctNum": 101,
        "MediaRuntimeTotalSeconds": 120,
        "CreatedAt": "2026-03-05 10:00:00",
        "FinishedAt": "2026-03-05 10:05:00",
    }


class TestWasabiFanOutEndpoints:
    @parameterized.expand(
        [
            ("details", "sub_account_invoice_items", ""),
            ("regional", "sub_account_invoice_regional_items", "/regional"),
        ]
    )
    def test_sub_invoice_items_walk_accounts_then_sub_invoices(self, _name: str, schema: str, suffix: str) -> None:
        result = _driver().run(
            schema,
            route(
                {
                    "/v1/accounts": [ScriptedResponse(json=[{"AcctNum": 101}, {"AcctNum": 102}])],
                    "/v1/accounts/101/invoices": [
                        ScriptedResponse(json=[{**_SUB_INVOICE_PARENT, "SubInvoiceNum": 5001}])
                    ],
                    "/v1/accounts/102/invoices": [
                        ScriptedResponse(json=[{**_SUB_INVOICE_PARENT, "AcctNum": 102, "SubInvoiceNum": 5002}])
                    ],
                    f"/v1/accounts/101/invoices/5001{suffix}": [
                        ScriptedResponse(
                            json={
                                "SubInvoice": {**_SUB_INVOICE_PARENT, "SubInvoiceNum": 5001},
                                "SubInvoiceItems": [_sub_invoice_item(1, 5001), _sub_invoice_item(2, 5001)],
                            }
                        )
                    ],
                    # A sub-invoice removed between its listing and the detail fetch.
                    f"/v1/accounts/102/invoices/5002{suffix}": [
                        ScriptedResponse(status=404, json={"Msg": "Not Found"})
                    ],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [
            {**_sub_invoice_item(1, 5001), **_SUB_INVOICE_PARENT},
            {**_sub_invoice_item(2, 5001), **_SUB_INVOICE_PARENT},
        ]

    @parameterized.expand(
        [
            ("full_refresh", None, None, None),
            ("incremental", "2026-03-05 10:05:00", "2026-03-05", (TODAY + timedelta(days=1)).isoformat()),
        ]
    )
    def test_air_jobs_pages_each_account_until_an_empty_page(
        self, _name: str, last_value: str | None, expected_from: str | None, expected_to: str | None
    ) -> None:
        with time_machine.travel(datetime.combine(TODAY, datetime.min.time(), UTC), tick=False):
            result = _driver().run(
                "air_jobs",
                route(
                    {
                        "/v1/accounts": [ScriptedResponse(json=[{"AcctNum": 101}, {"AcctNum": 102}])],
                        "/v1/accounts/101/air-jobs": [
                            ScriptedResponse(
                                json=[
                                    {
                                        "Pagination": {
                                            "PageSize": 100,
                                            "PageNumber": 0,
                                            "TotalRecords": 2,
                                            "TotalPages": 2,
                                        },
                                        "Records": [_air_job("job-1")],
                                    }
                                ]
                            ),
                            # Wasabi reports TotalPages as -1 on every page after the first.
                            ScriptedResponse(
                                json=[
                                    {
                                        "Pagination": {
                                            "PageSize": 100,
                                            "PageNumber": 1,
                                            "TotalRecords": -1,
                                            "TotalPages": -1,
                                        },
                                        "Records": [_air_job("job-2")],
                                    }
                                ]
                            ),
                            ScriptedResponse(json=[{"Pagination": {}, "Records": []}]),
                        ],
                        # A bare object body is accepted too.
                        "/v1/accounts/102/air-jobs": [ScriptedResponse(json={"Pagination": {}, "Records": []})],
                    }
                ),
                should_use_incremental_field=last_value is not None,
                incremental_field="FinishedAt",
                db_incremental_field_last_value=last_value,
            )

        assert result.raised is None
        assert result.rows == [_air_job("job-1"), _air_job("job-2")]
        assert result.response is not None
        # Rows restart at each account, so the run is not one ascending series.
        assert result.response.sort_mode is None
        job_requests = [r for r in result.requests if r.path.endswith("/air-jobs")]
        assert [r.param("pageNumber") for r in job_requests] == ["0", "1", "2", "0"]
        assert {r.param("from") for r in job_requests} == {expected_from}
        assert {r.param("to") for r in job_requests} == {expected_to}
