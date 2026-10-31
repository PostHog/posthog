from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import pytest
from unittest import mock

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.adobe_analytics.adobe_analytics import (
    AdobeAnalyticsClient,
    AdobeAnalyticsResumeConfig,
    metric_column_names,
    parse_date,
    parse_metrics,
    report_rows,
    resolve_window,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adobe_analytics.source import AdobeAnalyticsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.adobeanalytics import (
    AdobeAnalyticsSourceConfig,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.adobe_analytics.adobe_analytics"

_LOGGER = cast(FilteringBoundLogger, mock.MagicMock())


def _driver(start_date: str | None = None) -> SourceDriver:
    return SourceDriver(
        AdobeAnalyticsSource(),
        AdobeAnalyticsSourceConfig(
            client_id="cid",
            client_secret="sec",
            global_company_id="gcid",
            report_suite_id="rs1",
            start_date=start_date,
        ),
    )


def _token() -> ScriptedResponse:
    return ScriptedResponse(json={"access_token": "tok", "expires_in": 86399})


def _report_payload(rows: list[dict[str, Any]], last_page: bool = True, total_pages: int | None = 1) -> dict[str, Any]:
    payload: dict[str, Any] = {"rows": rows, "lastPage": last_page}
    if total_pages is not None:
        payload["totalPages"] = total_pages
    return payload


class TestParseDate:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), date(2024, 1, 2)),
            (datetime(2024, 1, 2, 3, 4, 5), date(2024, 1, 2)),
            (date(2024, 1, 2), date(2024, 1, 2)),
            ("2024-01-02", date(2024, 1, 2)),
            ("2024-01-02T03:04:05Z", date(2024, 1, 2)),
            ("", None),
            (None, None),
            ("not-a-date", None),
        ],
    )
    def test_parse_date(self, value: Any, expected: date | None) -> None:
        assert parse_date(value) == expected


class TestParseMetrics:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (None, ["metrics/visits", "metrics/visitors", "metrics/pageviews"]),
            ("", ["metrics/visits", "metrics/visitors", "metrics/pageviews"]),
            ("  ,  ", ["metrics/visits", "metrics/visitors", "metrics/pageviews"]),
            ("metrics/visits", ["metrics/visits"]),
            (" metrics/visits , metrics/orders ", ["metrics/visits", "metrics/orders"]),
        ],
    )
    def test_parse_metrics(self, raw: str | None, expected: list[str]) -> None:
        assert parse_metrics(raw) == expected


class TestMetricColumnNames:
    @pytest.mark.parametrize(
        "metric_ids, expected",
        [
            (["metrics/visits", "metrics/pageviews"], ["visits", "pageviews"]),
            (["cm300000123_5f8a"], ["cm300000123_5f8a"]),
            (["metrics/event1.2"], ["event1_2"]),
            # Two different metric ids can collapse to the same leaf; keep both columns.
            (["metrics/visits", "other/visits"], ["visits", "visits_2"]),
        ],
    )
    def test_metric_column_names(self, metric_ids: list[str], expected: list[str]) -> None:
        assert metric_column_names(metric_ids) == expected


class TestResolveWindow:
    @pytest.mark.parametrize(
        "start_date, incremental, last_value, expected_start",
        [
            # Adobe restates recent days, so an incremental run re-reads one trailing day.
            (None, True, "2024-03-05", date(2024, 3, 4)),
            ("2024-01-01", True, "2024-03-05", date(2024, 3, 4)),
            # No watermark yet — fall back to the configured start date.
            ("2024-01-01", True, None, date(2024, 1, 1)),
            ("2024-01-01", False, "2024-03-05", date(2024, 1, 1)),
            # Nothing configured — backfill the default window.
            (None, False, None, date(2023, 12, 7)),
            # A start date in the future must not produce an inverted window.
            ("2099-01-01", False, None, date(2024, 3, 6)),
            # An ancient start date is clamped to the maximum backfill window so we
            # don't issue hundreds of thousands of sequential day requests.
            ("0001-01-01", False, None, date(2024, 3, 6) - timedelta(days=365 * 3)),
            ("0001-01-01", True, "0001-01-02", date(2024, 3, 6) - timedelta(days=365 * 3)),
        ],
    )
    def test_resolve_window(
        self, start_date: str | None, incremental: bool, last_value: str | None, expected_start: date
    ) -> None:
        today = date(2024, 3, 6)
        window = resolve_window(start_date, incremental, last_value, today)
        assert window.start == expected_start
        assert window.end == today


class TestReportRows:
    def test_metric_columns_are_positional(self) -> None:
        payload = _report_payload([{"itemId": "1", "value": "Home", "data": [10, 20]}])

        rows = report_rows(payload, "rs1", date(2024, 1, 1), "variables/page", ["visits", "orders"])

        assert rows == [
            {
                "rsid": "rs1",
                "date": "2024-01-01",
                "dimension": "variables/page",
                "item_id": "1",
                "value": "Home",
                "visits": 10,
                "orders": 20,
            }
        ]

    def test_missing_metric_values_are_null_not_dropped(self) -> None:
        payload = _report_payload([{"itemId": 7, "value": "Home", "data": [10]}])

        rows = report_rows(payload, "rs1", date(2024, 1, 1), "variables/page", ["visits", "orders"])

        assert rows[0]["item_id"] == "7"
        assert rows[0]["orders"] is None


class TestClientAuth:
    def test_401_remints_the_token_once_and_retries(self) -> None:
        with scripted_network(
            [
                _token(),
                ScriptedResponse(status=401, json={}),
                _token(),
                ScriptedResponse(json={"content": [{"id": "s1"}]}),
            ]
        ) as network:
            client = AdobeAnalyticsClient("cid", "sec", _LOGGER, "gcid", min_request_interval=0)

            assert client.get_json("/segments") == {"content": [{"id": "s1"}]}
            assert network.requests_log[0].path == "/ims/token/v3"
            assert [request.path for request in network.requests_log] == [
                "/ims/token/v3",
                "/api/gcid/segments",
                "/ims/token/v3",
                "/api/gcid/segments",
            ]

    def test_persistent_401_raises(self) -> None:
        with scripted_network(
            [_token(), ScriptedResponse(status=401), _token(), ScriptedResponse(status=401)]
        ) as network:
            client = AdobeAnalyticsClient("cid", "sec", _LOGGER, "gcid", min_request_interval=0)

            with pytest.raises(requests.HTTPError):
                client.get_json("/segments")
            assert [request.path for request in network.requests_log] == [
                "/ims/token/v3",
                "/api/gcid/segments",
                "/ims/token/v3",
                "/api/gcid/segments",
            ]

    @pytest.mark.parametrize("status", [400, 403, 404])
    def test_error_statuses_raise(self, status: int) -> None:
        with scripted_network([_token(), ScriptedResponse(status=status, json={})]) as network:
            client = AdobeAnalyticsClient("cid", "sec", _LOGGER, "gcid", min_request_interval=0)

            with pytest.raises(requests.HTTPError):
                client.get_json("/segments")
            assert [request.path for request in network.requests_log] == ["/ims/token/v3", "/api/gcid/segments"]


class TestGlobalCompanyIdDiscovery:
    @pytest.mark.parametrize("payload", [{}, {"imsOrgs": []}, {"imsOrgs": [{"companies": []}]}])
    def test_missing_company_raises_actionable_error(self, payload: dict[str, Any]) -> None:
        with scripted_network([_token(), ScriptedResponse(json=payload)]) as network:
            client = AdobeAnalyticsClient("cid", "sec", _LOGGER, None, min_request_interval=0)

            with pytest.raises(ValueError, match="global company ID"):
                client.resolve_global_company_id()
            assert [request.path for request in network.requests_log] == ["/ims/token/v3", "/discovery/me"]


class TestValidateCredentials:
    def test_valid_credentials(self) -> None:
        with scripted_network([_token(), ScriptedResponse(json={"content": []})]) as network:
            assert validate_credentials("cid", "sec", "gcid", _LOGGER) == (True, None)
            assert [request.path for request in network.requests_log] == [
                "/ims/token/v3",
                "/api/gcid/collections/suites",
            ]

    def test_bad_client_credentials_are_reported(self) -> None:
        with scripted_network(
            [_token(), ScriptedResponse(status=401), _token(), ScriptedResponse(status=401)]
        ) as network:
            valid, message = validate_credentials("cid", "sec", None, _LOGGER)

            assert valid is False
            assert message is not None and "client ID and secret" in message
            assert [request.path for request in network.requests_log] == [
                "/ims/token/v3",
                "/discovery/me",
                "/ims/token/v3",
                "/discovery/me",
            ]

    def test_missing_product_profile_is_reported(self) -> None:
        with scripted_network(
            [
                _token(),
                ScriptedResponse(json={"imsOrgs": [{"companies": [{"globalCompanyId": "gcid"}]}]}),
                ScriptedResponse(status=403, json={}),
            ]
        ) as network:
            valid, message = validate_credentials("cid", "sec", None, _LOGGER)

            assert valid is False
            assert message is not None and "product profile" in message
            assert [request.path for request in network.requests_log] == [
                "/ims/token/v3",
                "/discovery/me",
                "/api/gcid/collections/suites",
            ]


class TestMetadataEndpoints:
    def test_paginates_until_last_page_and_saves_state_between_pages(self) -> None:
        result = _driver().run(
            "segments",
            [
                _token(),
                ScriptedResponse(json={"content": [{"id": "s1"}], "lastPage": False}),
                ScriptedResponse(json={"content": [{"id": "s2"}], "lastPage": True}),
            ],
        )

        assert result.raised is None
        assert result.items == [[{"id": "s1"}], [{"id": "s2"}]]
        assert result.paths == ["/ims/token/v3", "/api/gcid/segments", "/api/gcid/segments"]
        assert result.params("page") == [None, "0", "1"]
        assert result.params("limit") == [None, "1000", "1000"]
        assert result.params("rsids") == [None, "rs1", "rs1"]
        assert result.saved_states == [AdobeAnalyticsResumeConfig(page=1)]
        assert result.final_state is None

    @pytest.mark.parametrize("endpoint, suite_param", [("dimensions", "rsid"), ("metrics", "rsid")])
    def test_bare_array_catalogs_are_single_shot_and_carry_the_report_suite(
        self, endpoint: str, suite_param: str
    ) -> None:
        result = _driver().run(endpoint, [_token(), ScriptedResponse(json=[{"id": "variables/page"}])])

        assert result.raised is None
        assert result.items == [[{"id": "variables/page", "rsid": "rs1"}]]
        assert result.paths == ["/ims/token/v3", f"/api/gcid/{endpoint}"]
        assert result.requests[1].query == {suite_param: ("rs1",)}
        assert result.final_state is None

    def test_annotations_request_expanded_fields_across_all_owners_on_every_page(self) -> None:
        result = _driver().run(
            "annotations",
            [
                _token(),
                ScriptedResponse(json={"content": [{"id": "a1", "name": "Launch"}], "lastPage": False}),
                ScriptedResponse(json={"content": [{"id": "a2", "name": "Outage"}], "lastPage": True}),
            ],
        )

        assert result.raised is None
        assert result.items == [[{"id": "a1", "name": "Launch"}], [{"id": "a2", "name": "Outage"}]]
        assert result.params("includeType") == [None, "all", "all"]
        for expansion in result.params("expansion")[1:]:
            assert expansion is not None
            assert {"name", "dateRange", "modifiedDate", "rsid"} <= set(expansion.split(","))

    def test_users_served_as_a_bare_array_are_yielded_once(self) -> None:
        result = _driver().run("users", [_token(), ScriptedResponse(json=[{"loginId": 1, "login": "jane"}])])

        assert result.raised is None
        assert result.items == [[{"loginId": 1, "login": "jane"}]]
        assert result.paths == ["/ims/token/v3", "/api/gcid/users"]
        assert result.final_state is None


class TestReportEndpoint:
    @mock.patch(f"{_MODULE}._today", return_value=date(2024, 1, 3))
    def test_resumes_mid_window_from_saved_day_and_page(self, _mock_today: mock.MagicMock) -> None:
        result = _driver(start_date="2024-01-01").run(
            "report",
            [_token(), ScriptedResponse(json=_report_payload([]))],
            resume_state=AdobeAnalyticsResumeConfig(page=2, next_date="2024-01-03"),
        )

        assert result.raised is None
        assert result.paths == ["/ims/token/v3", "/api/gcid/reports"]
        body = result.requests[1].json()
        assert body["globalFilters"][0]["dateRange"].startswith("2024-01-03")
        assert body["settings"]["page"] == 2

    @mock.patch(f"{_MODULE}._today", return_value=date(2024, 3, 6))
    def test_incremental_run_re_reads_the_restatement_window(self, _mock_today: mock.MagicMock) -> None:
        result = _driver(start_date="2020-01-01").run(
            "report",
            [_token(), *(ScriptedResponse(json=_report_payload([])) for _ in range(3))],
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-03-05",
        )

        assert result.raised is None
        assert result.paths == ["/ims/token/v3", "/api/gcid/reports", "/api/gcid/reports", "/api/gcid/reports"]
        days = [request.json()["globalFilters"][0]["dateRange"][:10] for request in result.requests[1:]]
        assert days == ["2024-03-04", "2024-03-05", "2024-03-06"]

    @mock.patch(f"{_MODULE}.MAX_REPORT_PAGES", 3)
    @mock.patch(f"{_MODULE}._today", return_value=date(2024, 1, 1))
    def test_page_cap_terminates_a_report_that_never_signals_completion(self, _mock_today: mock.MagicMock) -> None:
        # No `lastPage`, no `totalPages`, always rows — the cap is the only exit.
        page = ScriptedResponse(json={"rows": [{"itemId": "1", "value": "a", "data": [1]}]})
        result = _driver(start_date="2024-01-01").run("report", [_token(), page, page, page])

        assert result.raised is None
        assert len(result.items) == 3
        assert result.paths == ["/ims/token/v3", "/api/gcid/reports", "/api/gcid/reports", "/api/gcid/reports"]
        assert [request.json()["settings"]["page"] for request in result.requests[1:]] == [0, 1, 2]


class TestAdobeAnalyticsSourceResponse:
    def test_metadata_tables_are_not_datetime_partitioned(self) -> None:
        result = _driver().run("segments", [_token(), ScriptedResponse(json={"content": [], "lastPage": True})])

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.partition_mode is None
        assert response.partition_keys is None
