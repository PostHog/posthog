from datetime import UTC, datetime
from typing import Any, Optional

import time_machine

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.awin.awin import (
    AwinFanoutTarget,
    AwinResumeConfig,
    _build_window_params,
    _format_path,
    _rows_from_response,
    _to_datetime,
    _windows_for_account,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.awin.settings import AWIN_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.awin.source import AwinSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awin import AwinSourceConfig


def _counts(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


class TestToDatetime:
    @parameterized.expand(
        [
            ("none", None, None),
            ("naive_string", "2024-01-01T00:00:00", datetime(2024, 1, 1, tzinfo=UTC)),
            ("z_string", "2024-01-01T00:00:00Z", datetime(2024, 1, 1, tzinfo=UTC)),
            ("garbage", "not-a-date", None),
        ]
    )
    def test_to_datetime(self, _name: str, value: Any, expected: Optional[datetime]) -> None:
        assert _to_datetime(value) == expected


class TestWindowsForAccount:
    @parameterized.expand([("reports_advertiser",), ("reports_publisher",)])
    @time_machine.travel("2024-06-01", tick=False)
    def test_reports_use_lookback_window_regardless_of_incremental(self, endpoint: str) -> None:
        windows = _windows_for_account(AWIN_ENDPOINTS[endpoint], True, datetime(2020, 1, 1, tzinfo=UTC))
        # 30-day rolling snapshot ending now, not the stale 2020 cursor.
        assert windows is not None and len(windows) == 1
        assert windows[0] is not None
        assert windows[0][0] == datetime(2024, 5, 2, tzinfo=UTC)
        assert windows[0][1] == datetime(2024, 6, 1, tzinfo=UTC)

    @time_machine.travel("2024-06-01", tick=False)
    def test_future_cursor_yields_no_windows(self) -> None:
        windows = _windows_for_account(AWIN_ENDPOINTS["transactions"], True, datetime(2025, 1, 1, tzinfo=UTC))
        assert windows == []


class TestBuildWindowParams:
    def test_reports_advertiser_includes_region(self) -> None:
        # Awin's aggregated advertiser report 400s without `region` because it's a required param
        # the API has no "all regions" value for.
        params = _build_window_params(
            AWIN_ENDPOINTS["reports_advertiser"],
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2024, 1, 31, tzinfo=UTC),
            incremental_field=None,
            region="US",
        )
        assert params["region"] == "US"


class TestRowsFromResponse:
    def test_inject_publisher_id_when_configured(self) -> None:
        data = [{"id": 1}]
        rows = _rows_from_response(AWIN_ENDPOINTS["programmes"], data, AwinFanoutTarget(publisher_id=42))
        assert rows == [{"id": 1, "publisherId": 42}]

    def test_inject_does_not_overwrite_existing_publisher_id(self) -> None:
        data = [{"id": 1, "publisherId": 7}]
        rows = _rows_from_response(AWIN_ENDPOINTS["programmes"], data, AwinFanoutTarget(publisher_id=42))
        assert rows == [{"id": 1, "publisherId": 7}]

    def test_commission_groups_flattens_envelope_onto_each_group(self) -> None:
        # Awin hangs the rate validity window off the envelope, not off each group, so without the
        # copy every commission_groups row loses when its rate applied.
        data = {
            "advertiser": 9,
            "publisher": 42,
            "ratesStart": "2024-01-01T00:00:00Z",
            "ratesEnd": "2024-06-01T00:00:00Z",
            "commissionGroups": [{"groupId": 1, "type": "fix"}, {"groupId": 2, "type": "percentage"}],
        }
        rows = _rows_from_response(
            AWIN_ENDPOINTS["commission_groups"], data, AwinFanoutTarget(publisher_id=42, advertiser_id=9)
        )

        assert rows == [
            {
                "groupId": 1,
                "type": "fix",
                "ratesStart": "2024-01-01T00:00:00Z",
                "ratesEnd": "2024-06-01T00:00:00Z",
                "publisherId": 42,
                "advertiserId": 9,
            },
            {
                "groupId": 2,
                "type": "percentage",
                "ratesStart": "2024-01-01T00:00:00Z",
                "ratesEnd": "2024-06-01T00:00:00Z",
                "publisherId": 42,
                "advertiserId": 9,
            },
        ]

    def test_advertiser_publishers_gets_the_advertiser_id_injected(self) -> None:
        # The rows carry only the publisher's own fields, so without this the lookup can't be joined
        # back to the advertiser it belongs to.
        data = [{"id": 7, "name": "Some publisher"}]
        rows = _rows_from_response(AWIN_ENDPOINTS["advertiser_publishers"], data, AwinFanoutTarget(advertiser_id=90))
        assert rows == [{"id": 7, "name": "Some publisher", "advertiserId": 90}]


class TestDiscoverAccountIds:
    @parameterized.expand([("publisher", [1, 3]), ("advertiser", [2])])
    def test_filters_by_account_type_and_sorts_and_dedupes(self, account_type: str, expected: list[int]) -> None:
        accounts = [
            {"accountId": 3, "accountType": "publisher"},
            {"accountId": 1, "accountType": "publisher"},
            {"accountId": 2, "accountType": "advertiser"},
            {"accountId": 1, "accountType": "publisher"},
        ]

        def answer(request: RecordedRequest) -> ScriptedResponse:
            return ScriptedResponse(json={"accounts": accounts} if request.path == "/accounts" else [])

        endpoint = "programmes" if account_type == "publisher" else "advertiser_publishers"
        result = SourceDriver(AwinSource(), AwinSourceConfig(api_token="token")).run(endpoint, answer)

        assert result.raised is None
        assert result.paths[1:] == [
            f"/{'publishers' if account_type == 'publisher' else 'advertisers'}/{account_id}/"
            f"{'programmes' if account_type == 'publisher' else 'publishers'}"
            for account_id in expected
        ]


class TestFormatPath:
    @parameterized.expand(
        [
            ("transactions", AwinFanoutTarget(publisher_id=5), "/publishers/5/transactions/"),
            (
                "commission_groups",
                AwinFanoutTarget(publisher_id=5, advertiser_id=9),
                "/publishers/5/commissiongroups",
            ),
            ("reports_publisher", AwinFanoutTarget(advertiser_id=9), "/advertisers/9/reports/publisher"),
            ("advertiser_publishers", AwinFanoutTarget(advertiser_id=9), "/advertisers/9/publishers"),
        ]
    )
    def test_each_id_lands_in_the_path_segment_that_accepts_it(
        self, endpoint: str, target: AwinFanoutTarget, expected: str
    ) -> None:
        # A programme-scoped path holds both ids, so a template naming the wrong one reads another
        # account rather than failing loudly.
        assert _format_path(AWIN_ENDPOINTS[endpoint], target) == expected


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_maps_to_bool(self, _name: str, status: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            assert validate_credentials("token") is expected
        assert [request.path for request in network.requests_log] == ["/accounts"]

    def test_exception_is_false(self) -> None:
        with scripted_network(always(ConnectionResetError("boom"))) as network:
            assert validate_credentials("token") is False
        assert {request.path for request in network.requests_log} == {"/accounts"}


class TestGetRows:
    def test_accounts_endpoint_yields_accounts_without_fanout(self) -> None:
        result = SourceDriver(AwinSource(), AwinSourceConfig(api_token="token")).run(
            "accounts", [ScriptedResponse(json={"accounts": [{"accountId": 1}]})]
        )

        assert result.raised is None
        assert result.items == [[{"accountId": 1}]]
        # A single call to /accounts, no per-publisher fan-out.
        assert result.paths == ["/accounts"]

    @time_machine.travel("2024-06-01", tick=False)
    def test_windowed_fanout_arrives_in_globally_ascending_order(self) -> None:
        # Two accounts, multiple 30-day windows each. To keep the asc watermark monotonic, every
        # account's window N must be fetched before any account's window N+1 (windows OUTER, accounts
        # INNER) — not one account fully before the next.
        def answer(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/accounts":
                return ScriptedResponse(
                    json={
                        "accounts": [
                            {"accountId": 10, "accountType": "publisher"},
                            {"accountId": 20, "accountType": "publisher"},
                        ]
                    }
                )
            return ScriptedResponse(json=[{"id": 1}])

        result = SourceDriver(AwinSource(), AwinSourceConfig(api_token="token")).run("transactions", answer)
        starts = [request.param("startDate") or "" for request in result.requests[1:]]

        # startDate is non-decreasing across the whole run despite fanning out over two accounts.
        assert result.raised is None
        assert starts == sorted(starts)
        # Each window's startDate appears once per account (two accounts).
        assert all(count == 2 for count in _counts(starts).values())

    @time_machine.travel("2024-06-01", tick=False)
    def test_no_publisher_accounts_yields_nothing(self) -> None:
        result = SourceDriver(AwinSource(), AwinSourceConfig(api_token="token")).run(
            "programmes", [ScriptedResponse(json={"accounts": []})]
        )
        assert result.raised is None
        assert result.items == []
        assert result.paths == ["/accounts"]

    @time_machine.travel("2024-06-01", tick=False)
    def test_advertiser_fanout_skips_publisher_accounts(self) -> None:
        # /advertisers paths only accept advertiser accounts; fanning out over publisher ids 404s.
        result = SourceDriver(AwinSource(), AwinSourceConfig(api_token="token")).run(
            "advertiser_publishers",
            [
                ScriptedResponse(
                    json={
                        "accounts": [
                            {"accountId": 10, "accountType": "publisher"},
                            {"accountId": 90, "accountType": "advertiser"},
                        ]
                    }
                ),
                ScriptedResponse(json=[{"id": 7}]),
            ],
        )

        assert result.raised is None
        assert result.paths[1:] == ["/advertisers/90/publishers"]
        assert result.items == [[{"id": 7, "advertiserId": 90}]]

    @time_machine.travel("2024-06-01", tick=False)
    def test_programme_fanout_resumes_at_the_saved_pair(self) -> None:
        result = SourceDriver(AwinSource(), AwinSourceConfig(api_token="token")).run(
            "programme_details",
            [
                ScriptedResponse(json={"accounts": [{"accountId": 10, "accountType": "publisher"}]}),
                ScriptedResponse(json=[{"id": 1}, {"id": 2}, {"id": 3}]),
                ScriptedResponse(json={}),
                ScriptedResponse(json={}),
            ],
            resume_state=AwinResumeConfig(publisher_id=10, advertiser_id=2, window_start=None),
        )

        # Programme 1 was already done before the crash; the pair bookmark restarts at 2.
        assert result.raised is None
        assert result.params("advertiserId")[2:] == ["2", "3"]


class TestAwinSource:
    @parameterized.expand(
        [
            ("accounts", ["accountId"], None),
            ("programmes", ["publisherId", "id"], None),
            ("transactions", ["id"], "transactionDate"),
            ("reports_advertiser", ["publisherId", "advertiserId"], None),
            ("reports_publisher", ["advertiserId", "publisherId"], None),
            ("advertiser_publishers", ["advertiserId", "id"], None),
            ("commission_groups", ["publisherId", "advertiserId", "groupId"], None),
            ("programme_details", ["publisherId", "advertiserId"], None),
        ]
    )
    def test_source_response_shape(self, endpoint: str, expected_pks: list[str], partition_key: Optional[str]) -> None:
        result = SourceDriver(AwinSource(), AwinSourceConfig(api_token="token")).run(
            endpoint, [ScriptedResponse(json={"accounts": []})]
        )
        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == expected_pks
        if partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
            assert response.partition_format == "month"
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
