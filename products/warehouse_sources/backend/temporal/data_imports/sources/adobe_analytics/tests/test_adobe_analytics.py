import contextlib
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import pytest
from unittest import mock

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.adobe_analytics.adobe_analytics import (
    ANALYTICS_HOST,
    DISCOVERY_URL,
    IMS_TOKEN_URL,
    AdobeAnalyticsClient,
    AdobeAnalyticsResumeConfig,
    adobe_analytics_source,
    build_report_body,
    get_rows,
    metric_column_names,
    parse_date,
    parse_metrics,
    report_rows,
    resolve_window,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.adobe_analytics.settings import (
    ADOBE_ANALYTICS_ENDPOINTS,
    ENDPOINTS,
    REPORT_PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.adobe_analytics.adobe_analytics"

_LOGGER = cast(FilteringBoundLogger, mock.MagicMock())


class FakeResumeManager(ResumableSourceManager[AdobeAnalyticsResumeConfig]):
    """In-memory stand-in for the Redis-backed manager."""

    def __init__(self, state: AdobeAnalyticsResumeConfig | None = None) -> None:
        self.state = state
        self.saved: list[AdobeAnalyticsResumeConfig] = []
        self.cleared = 0

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> AdobeAnalyticsResumeConfig | None:
        return self.state

    def save_state(self, data: AdobeAnalyticsResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared += 1


def _response(body: Any, status: int = 200) -> mock.MagicMock:
    response = mock.MagicMock()
    response.json.return_value = body
    response.status_code = status
    response.ok = status < 400
    response.text = ""
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status} Client Error", response=cast(requests.Response, response)
        )
    else:
        response.raise_for_status.return_value = None
    return response


def _report_payload(rows: list[dict[str, Any]], last_page: bool = True, total_pages: int | None = 1) -> dict[str, Any]:
    payload: dict[str, Any] = {"rows": rows, "lastPage": last_page}
    if total_pages is not None:
        payload["totalPages"] = total_pages
    return payload


@contextlib.contextmanager
def _sessions() -> Iterator[tuple[mock.MagicMock, mock.MagicMock]]:
    """Patch the tracked-session factory, splitting the API session from the token-exchange one."""
    api = mock.MagicMock()
    auth = mock.MagicMock()
    auth.post.return_value = _response({"access_token": "tok", "expires_in": 86399})

    def factory(**kwargs: Any) -> mock.MagicMock:
        return auth if kwargs.get("capture") is False else api

    with mock.patch(f"{_MODULE}.make_tracked_session", side_effect=factory):
        yield api, auth


@pytest.fixture(autouse=True)
def _no_sleep() -> Iterator[mock.MagicMock]:
    with mock.patch(f"{_MODULE}.time.sleep") as sleep:
        yield sleep


def _get_rows(
    api_side_effect: list[mock.MagicMock] | None,
    post_side_effect: list[mock.MagicMock] | None,
    endpoint: str,
    manager: FakeResumeManager,
    **overrides: Any,
) -> list[list[dict[str, Any]]]:
    with _sessions() as (api, _auth):
        if api_side_effect is not None:
            api.get.side_effect = api_side_effect
        if post_side_effect is not None:
            api.post.side_effect = post_side_effect
        kwargs: dict[str, Any] = {
            "client_id": "cid",
            "client_secret": "sec",
            "global_company_id": "gcid",
            "report_suite_id": "rs1",
            "report_dimension": None,
            "report_metrics": None,
            "start_date": None,
            "endpoint": endpoint,
            "logger": _LOGGER,
            "resumable_source_manager": manager,
        }
        kwargs.update(overrides)
        batches = list(get_rows(**kwargs))
    return batches


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


class TestBuildReportBody:
    def test_body_scopes_a_single_day_and_page(self) -> None:
        body = build_report_body("rs1", "variables/page", ["metrics/visits", "metrics/orders"], date(2024, 1, 31), 2)

        assert body["rsid"] == "rs1"
        assert body["dimension"] == "variables/page"
        assert body["globalFilters"] == [
            {"type": "dateRange", "dateRange": "2024-01-31T00:00:00.000/2024-02-01T00:00:00.000"}
        ]
        assert body["metricContainer"]["metrics"] == [
            {"columnId": "0", "id": "metrics/visits"},
            {"columnId": "1", "id": "metrics/orders"},
        ]
        assert body["settings"]["page"] == 2
        assert body["settings"]["limit"] == REPORT_PAGE_SIZE


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

    def test_empty_report_yields_no_rows(self) -> None:
        assert report_rows({"rows": []}, "rs1", date(2024, 1, 1), "variables/page", ["visits"]) == []


class TestClientAuth:
    def test_token_is_minted_once_and_sent_with_the_api_key(self) -> None:
        with _sessions() as (api, auth):
            api.get.return_value = _response({"content": []})
            client = AdobeAnalyticsClient("cid", "sec", _LOGGER, "gcid", min_request_interval=0)

            client.get_json("/segments")
            client.get_json("/segments")

            assert auth.post.call_count == 1
            assert auth.post.call_args.args[0] == IMS_TOKEN_URL
            assert auth.post.call_args.kwargs["data"]["grant_type"] == "client_credentials"
            headers = api.get.call_args.kwargs["headers"]
            assert headers["Authorization"] == "Bearer tok"
            assert headers["x-api-key"] == "cid"

    def test_401_remints_the_token_once_and_retries(self) -> None:
        with _sessions() as (api, auth):
            api.get.side_effect = [_response({}, 401), _response({"content": [{"id": "s1"}]})]
            client = AdobeAnalyticsClient("cid", "sec", _LOGGER, "gcid", min_request_interval=0)

            assert client.get_json("/segments") == {"content": [{"id": "s1"}]}
            assert auth.post.call_count == 2
            assert api.get.call_count == 2

    def test_persistent_401_raises(self) -> None:
        with _sessions() as (api, _auth):
            api.get.side_effect = [_response({}, 401), _response({}, 401)]
            client = AdobeAnalyticsClient("cid", "sec", _LOGGER, "gcid", min_request_interval=0)

            with pytest.raises(requests.HTTPError):
                client.get_json("/segments")

    @pytest.mark.parametrize("status", [400, 403, 404])
    def test_error_statuses_raise(self, status: int) -> None:
        with _sessions() as (api, _auth):
            api.get.return_value = _response({}, status)
            client = AdobeAnalyticsClient("cid", "sec", _LOGGER, "gcid", min_request_interval=0)

            with pytest.raises(requests.HTTPError):
                client.get_json("/segments")

    def test_requests_are_paced_under_the_throttle(self, _no_sleep: mock.MagicMock) -> None:
        with _sessions() as (api, _auth):
            api.get.return_value = _response({"content": []})
            client = AdobeAnalyticsClient("cid", "sec", _LOGGER, "gcid")

            client.get_json("/segments")
            client.get_json("/segments")

            assert _no_sleep.call_count >= 1
            assert _no_sleep.call_args.args[0] <= 0.5


class TestGlobalCompanyIdDiscovery:
    def test_configured_id_skips_discovery(self) -> None:
        with _sessions() as (api, _auth):
            client = AdobeAnalyticsClient("cid", "sec", _LOGGER, "gcid", min_request_interval=0)

            assert client.base_url == f"{ANALYTICS_HOST}/api/gcid"
            api.get.assert_not_called()

    def test_discovers_from_discovery_me(self) -> None:
        with _sessions() as (api, _auth):
            api.get.return_value = _response({"imsOrgs": [{"companies": [{"globalCompanyId": "discovered"}]}]})
            client = AdobeAnalyticsClient("cid", "sec", _LOGGER, None, min_request_interval=0)

            assert client.resolve_global_company_id() == "discovered"
            assert api.get.call_args.args[0] == DISCOVERY_URL
            # Cached — a second call must not re-probe discovery.
            assert client.resolve_global_company_id() == "discovered"
            assert api.get.call_count == 1

    @pytest.mark.parametrize("payload", [{}, {"imsOrgs": []}, {"imsOrgs": [{"companies": []}]}])
    def test_missing_company_raises_actionable_error(self, payload: dict[str, Any]) -> None:
        with _sessions() as (api, _auth):
            api.get.return_value = _response(payload)
            client = AdobeAnalyticsClient("cid", "sec", _LOGGER, None, min_request_interval=0)

            with pytest.raises(ValueError, match="global company ID"):
                client.resolve_global_company_id()


class TestValidateCredentials:
    def test_valid_credentials(self) -> None:
        with _sessions() as (api, _auth):
            api.get.return_value = _response({"content": []})

            assert validate_credentials("cid", "sec", "gcid", _LOGGER) == (True, None)

    def test_bad_client_credentials_are_reported(self) -> None:
        with _sessions() as (api, _auth):
            api.get.return_value = _response({}, 401)

            valid, message = validate_credentials("cid", "sec", None, _LOGGER)

            assert valid is False
            assert message is not None and "client ID and secret" in message

    def test_missing_product_profile_is_reported(self) -> None:
        with _sessions() as (api, _auth):
            api.get.side_effect = [
                _response({"imsOrgs": [{"companies": [{"globalCompanyId": "gcid"}]}]}),
                _response({}, 403),
            ]

            valid, message = validate_credentials("cid", "sec", None, _LOGGER)

            assert valid is False
            assert message is not None and "product profile" in message


class TestMetadataEndpoints:
    def test_paginates_until_last_page_and_saves_state_between_pages(self) -> None:
        manager = FakeResumeManager()

        batches = _get_rows(
            [
                _response({"content": [{"id": "s1"}], "lastPage": False}),
                _response({"content": [{"id": "s2"}], "lastPage": True}),
            ],
            None,
            "segments",
            manager,
        )

        assert batches == [[{"id": "s1"}], [{"id": "s2"}]]
        assert manager.saved == [AdobeAnalyticsResumeConfig(page=1)]
        assert manager.cleared == 1

    def test_stops_on_an_empty_page_when_last_page_is_not_flagged(self) -> None:
        manager = FakeResumeManager()

        batches = _get_rows(
            [
                _response({"content": [{"id": "s1"}]}),
                _response({"content": []}),
            ],
            None,
            "segments",
            manager,
        )

        assert batches == [[{"id": "s1"}]]
        assert manager.cleared == 1

    def test_scopes_the_request_to_the_report_suite(self) -> None:
        manager = FakeResumeManager()

        with _sessions() as (api, _auth):
            api.get.return_value = _response({"content": [], "lastPage": True})
            list(
                get_rows(
                    client_id="cid",
                    client_secret="sec",
                    global_company_id="gcid",
                    report_suite_id="rs1",
                    report_dimension=None,
                    report_metrics=None,
                    start_date=None,
                    endpoint="segments",
                    logger=_LOGGER,
                    resumable_source_manager=manager,
                )
            )

            assert api.get.call_args.args[0] == f"{ANALYTICS_HOST}/api/gcid/segments"
            assert api.get.call_args.kwargs["params"]["rsids"] == "rs1"
            assert api.get.call_args.kwargs["params"]["page"] == 0

    def test_resumes_from_the_saved_page(self) -> None:
        manager = FakeResumeManager(AdobeAnalyticsResumeConfig(page=4))

        with _sessions() as (api, _auth):
            api.get.return_value = _response({"content": [{"id": "s1"}], "lastPage": True})
            list(
                get_rows(
                    client_id="cid",
                    client_secret="sec",
                    global_company_id="gcid",
                    report_suite_id="rs1",
                    report_dimension=None,
                    report_metrics=None,
                    start_date=None,
                    endpoint="segments",
                    logger=_LOGGER,
                    resumable_source_manager=manager,
                )
            )

            assert api.get.call_args.kwargs["params"]["page"] == 4

    @pytest.mark.parametrize("endpoint, suite_param", [("dimensions", "rsid"), ("metrics", "rsid")])
    def test_bare_array_catalogs_are_single_shot_and_carry_the_report_suite(
        self, endpoint: str, suite_param: str
    ) -> None:
        manager = FakeResumeManager()

        with _sessions() as (api, _auth):
            api.get.return_value = _response([{"id": "variables/page"}])
            batches = list(
                get_rows(
                    client_id="cid",
                    client_secret="sec",
                    global_company_id="gcid",
                    report_suite_id="rs1",
                    report_dimension=None,
                    report_metrics=None,
                    start_date=None,
                    endpoint=endpoint,
                    logger=_LOGGER,
                    resumable_source_manager=manager,
                )
            )

            assert batches == [[{"id": "variables/page", "rsid": "rs1"}]]
            assert api.get.call_count == 1
            assert api.get.call_args.kwargs["params"] == {suite_param: "rs1"}
            assert manager.cleared == 1

    def test_report_suites_are_not_scoped_to_a_suite(self) -> None:
        manager = FakeResumeManager()

        with _sessions() as (api, _auth):
            api.get.return_value = _response({"content": [{"rsid": "rs1"}], "lastPage": True})
            list(
                get_rows(
                    client_id="cid",
                    client_secret="sec",
                    global_company_id="gcid",
                    report_suite_id="rs1",
                    report_dimension=None,
                    report_metrics=None,
                    start_date=None,
                    endpoint="report_suites",
                    logger=_LOGGER,
                    resumable_source_manager=manager,
                )
            )

            assert "rsids" not in api.get.call_args.kwargs["params"]


class TestReportEndpoint:
    @mock.patch(f"{_MODULE}._today", return_value=date(2024, 1, 3))
    def test_walks_day_windows_ascending_and_checkpoints_each_day(self, _mock_today: mock.MagicMock) -> None:
        manager = FakeResumeManager()

        with _sessions() as (api, _auth):
            api.post.side_effect = [
                _response(_report_payload([{"itemId": "1", "value": "2024-01-02", "data": [1, 2, 3]}])),
                _response(_report_payload([{"itemId": "2", "value": "2024-01-03", "data": [4, 5, 6]}])),
            ]
            batches = list(
                get_rows(
                    client_id="cid",
                    client_secret="sec",
                    global_company_id="gcid",
                    report_suite_id="rs1",
                    report_dimension=None,
                    report_metrics=None,
                    start_date="2024-01-02",
                    endpoint="report",
                    logger=_LOGGER,
                    resumable_source_manager=manager,
                )
            )

            assert [row["date"] for batch in batches for row in batch] == ["2024-01-02", "2024-01-03"]
            assert batches[0][0]["visits"] == 1
            assert batches[0][0]["pageviews"] == 3
            bodies = [call.kwargs["json"] for call in api.post.call_args_list]
            assert [body["globalFilters"][0]["dateRange"].split("/")[0][:10] for body in bodies] == [
                "2024-01-02",
                "2024-01-03",
            ]
            # Checkpoint advances to the next unfetched day, never past the window.
            assert manager.saved == [AdobeAnalyticsResumeConfig(page=0, next_date="2024-01-03")]
            assert manager.cleared == 1

    @mock.patch(f"{_MODULE}._today", return_value=date(2024, 1, 1))
    def test_pages_within_a_day_before_advancing(self, _mock_today: mock.MagicMock) -> None:
        manager = FakeResumeManager()

        with _sessions() as (api, _auth):
            api.post.side_effect = [
                _response(
                    _report_payload([{"itemId": "1", "value": "a", "data": [1]}], last_page=False, total_pages=2)
                ),
                _response(_report_payload([{"itemId": "2", "value": "b", "data": [2]}], last_page=True, total_pages=2)),
            ]
            batches = list(
                get_rows(
                    client_id="cid",
                    client_secret="sec",
                    global_company_id="gcid",
                    report_suite_id="rs1",
                    report_dimension="variables/page",
                    report_metrics="metrics/visits",
                    start_date="2024-01-01",
                    endpoint="report",
                    logger=_LOGGER,
                    resumable_source_manager=manager,
                )
            )

            assert len(batches) == 2
            assert [call.kwargs["json"]["settings"]["page"] for call in api.post.call_args_list] == [0, 1]
            assert manager.saved == [AdobeAnalyticsResumeConfig(page=1, next_date="2024-01-01")]

    @mock.patch(f"{_MODULE}._today", return_value=date(2024, 1, 3))
    def test_resumes_mid_window_from_saved_day_and_page(self, _mock_today: mock.MagicMock) -> None:
        manager = FakeResumeManager(AdobeAnalyticsResumeConfig(page=2, next_date="2024-01-03"))

        with _sessions() as (api, _auth):
            api.post.return_value = _response(_report_payload([]))
            list(
                get_rows(
                    client_id="cid",
                    client_secret="sec",
                    global_company_id="gcid",
                    report_suite_id="rs1",
                    report_dimension=None,
                    report_metrics=None,
                    start_date="2024-01-01",
                    endpoint="report",
                    logger=_LOGGER,
                    resumable_source_manager=manager,
                )
            )

            assert api.post.call_count == 1
            body = api.post.call_args.kwargs["json"]
            assert body["globalFilters"][0]["dateRange"].startswith("2024-01-03")
            assert body["settings"]["page"] == 2

    @mock.patch(f"{_MODULE}._today", return_value=date(2024, 1, 3))
    def test_stale_resume_state_outside_the_window_is_ignored(self, _mock_today: mock.MagicMock) -> None:
        manager = FakeResumeManager(AdobeAnalyticsResumeConfig(page=5, next_date="2020-01-01"))

        with _sessions() as (api, _auth):
            api.post.return_value = _response(_report_payload([]))
            list(
                get_rows(
                    client_id="cid",
                    client_secret="sec",
                    global_company_id="gcid",
                    report_suite_id="rs1",
                    report_dimension=None,
                    report_metrics=None,
                    start_date="2024-01-03",
                    endpoint="report",
                    logger=_LOGGER,
                    resumable_source_manager=manager,
                )
            )

            body = api.post.call_args.kwargs["json"]
            assert body["globalFilters"][0]["dateRange"].startswith("2024-01-03")
            assert body["settings"]["page"] == 0

    @mock.patch(f"{_MODULE}._today", return_value=date(2024, 3, 6))
    def test_incremental_run_re_reads_the_restatement_window(self, _mock_today: mock.MagicMock) -> None:
        manager = FakeResumeManager()

        with _sessions() as (api, _auth):
            api.post.return_value = _response(_report_payload([]))
            list(
                get_rows(
                    client_id="cid",
                    client_secret="sec",
                    global_company_id="gcid",
                    report_suite_id="rs1",
                    report_dimension=None,
                    report_metrics=None,
                    start_date="2020-01-01",
                    endpoint="report",
                    logger=_LOGGER,
                    resumable_source_manager=manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value="2024-03-05",
                )
            )

            days = [call.kwargs["json"]["globalFilters"][0]["dateRange"][:10] for call in api.post.call_args_list]
            assert days == ["2024-03-04", "2024-03-05", "2024-03-06"]

    @mock.patch(f"{_MODULE}.MAX_REPORT_PAGES", 3)
    @mock.patch(f"{_MODULE}._today", return_value=date(2024, 1, 1))
    def test_page_cap_terminates_a_report_that_never_signals_completion(self, _mock_today: mock.MagicMock) -> None:
        manager = FakeResumeManager()

        with _sessions() as (api, _auth):
            # No `lastPage`, no `totalPages`, always rows — the cap is the only exit.
            api.post.return_value = _response({"rows": [{"itemId": "1", "value": "a", "data": [1]}]})
            batches = list(
                get_rows(
                    client_id="cid",
                    client_secret="sec",
                    global_company_id="gcid",
                    report_suite_id="rs1",
                    report_dimension=None,
                    report_metrics=None,
                    start_date="2024-01-01",
                    endpoint="report",
                    logger=_LOGGER,
                    resumable_source_manager=manager,
                )
            )

            assert len(batches) == 3
            assert api.post.call_count == 3


class TestAdobeAnalyticsSourceResponse:
    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_primary_keys_match_the_endpoint_catalog(self, endpoint: str) -> None:
        response = adobe_analytics_source(
            client_id="cid",
            client_secret="sec",
            global_company_id="gcid",
            report_suite_id="rs1",
            report_dimension=None,
            report_metrics=None,
            start_date=None,
            endpoint=endpoint,
            logger=_LOGGER,
            resumable_source_manager=FakeResumeManager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == ADOBE_ANALYTICS_ENDPOINTS[endpoint].primary_key
        assert response.sort_mode == "asc"

    def test_report_is_partitioned_on_the_stable_day_column(self) -> None:
        response = adobe_analytics_source(
            client_id="cid",
            client_secret="sec",
            global_company_id="gcid",
            report_suite_id="rs1",
            report_dimension=None,
            report_metrics=None,
            start_date=None,
            endpoint="report",
            logger=_LOGGER,
            resumable_source_manager=FakeResumeManager(),
        )

        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["date"]
        assert response.partition_format == "month"

    def test_metadata_tables_are_not_datetime_partitioned(self) -> None:
        response = adobe_analytics_source(
            client_id="cid",
            client_secret="sec",
            global_company_id="gcid",
            report_suite_id="rs1",
            report_dimension=None,
            report_metrics=None,
            start_date=None,
            endpoint="segments",
            logger=_LOGGER,
            resumable_source_manager=FakeResumeManager(),
        )

        assert response.partition_mode is None
        assert response.partition_keys is None
