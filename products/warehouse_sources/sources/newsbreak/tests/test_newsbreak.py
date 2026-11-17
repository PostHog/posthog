from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.sources.newsbreak._config import NewsBreakSourceConfig
from products.warehouse_sources.sources.newsbreak.newsbreak import (
    INVALID_TIMEZONE_ERROR,
    INVALID_TOKEN_ERROR,
    NO_ORGANIZATIONS_ERROR,
    PERMISSION_ERROR,
    UNREACHABLE_ERROR,
    NewsBreakResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.sources.newsbreak.source import NewsBreakSource
from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)

ADMIN_ORGS = "/org/admin-orgs"
ACCOUNTS = "/ad-account/getGroupsByOrgIds"
CAMPAIGNS = "/campaign/getList"
REPORT = "/reports/getIntegratedReport"

# 2024-03-01 00:00 UTC.
CREATED_2024_03_01 = "1709251200"
NOW = datetime(2024, 3, 16, 12, 0, tzinfo=UTC)


def _driver(org_ids: str | None = "10", report_timezone: str | None = None) -> SourceDriver:
    return SourceDriver(
        NewsBreakSource(),
        NewsBreakSourceConfig(access_token="nb_token", org_ids=org_ids, report_timezone=report_timezone),
    )


def _ok(data: Any) -> ScriptedResponse:
    return ScriptedResponse(json={"code": 0, "data": data})


def _accounts(*account_ids: str, created: str = CREATED_2024_03_01) -> ScriptedResponse:
    return _ok(
        {
            "list": [
                {
                    "id": "10",
                    "name": "Org",
                    "adAccounts": [
                        {"id": account_id, "name": f"A{account_id}", "createTime": created}
                        for account_id in account_ids
                    ],
                }
            ]
        }
    )


def _page(ids: list[str], has_next: bool) -> ScriptedResponse:
    return _ok({"rows": [{"id": row_id} for row_id in ids], "hasNext": has_next, "pageNo": 1, "pageSize": 500})


def _report(rows: list[dict[str, Any]]) -> ScriptedResponse:
    return _ok({"rows": rows, "aggregateData": []})


def _bodies(requests: list[RecordedRequest], path: str) -> list[Any]:
    return [request.json() for request in requests if request.path.endswith(path)]


class TestAdAccounts:
    @pytest.mark.parametrize(
        ("org_ids", "script", "expected_paths", "expected_org_ids"),
        [
            (
                None,
                {
                    ADMIN_ORGS: [_ok({"list": [{"id": "10", "name": "Org"}, {"id": 20, "name": "Other"}]})],
                    ACCOUNTS: [_accounts("2", "1")],
                },
                [ADMIN_ORGS, ACCOUNTS],
                ["10", "20"],
            ),
            ("10, 20\n10", {ACCOUNTS: [_accounts("2", "1")]}, [ACCOUNTS], ["10", "20"]),
        ],
    )
    def test_reads_the_accounts_of_the_organizations(
        self,
        org_ids: str | None,
        script: dict[str, list[ScriptedResponse]],
        expected_paths: list[str],
        expected_org_ids: list[str],
    ) -> None:
        result = _driver(org_ids=org_ids).run("ad_accounts", route(script))

        assert result.raised is None
        assert [path.removeprefix("/business-api/v1") for path in result.paths] == expected_paths
        assert list(result.requests[-1].query["orgIds"]) == expected_org_ids
        assert {request.headers["access-token"] for request in result.requests} == {"nb_token"}
        assert result.rows == [
            {"id": "1", "name": "A1", "createTime": CREATED_2024_03_01, "orgId": "10", "orgName": "Org"},
            {"id": "2", "name": "A2", "createTime": CREATED_2024_03_01, "orgId": "10", "orgName": "Org"},
        ]

    def test_no_admin_organizations_fails_the_run(self) -> None:
        result = _driver(org_ids=None).run("ad_accounts", route({ADMIN_ORGS: [_ok({"list": []})]}))

        assert str(result.raised) == NO_ORGANIZATIONS_ERROR


class TestListEndpoints:
    def test_walks_pages_of_each_account(self) -> None:
        result = _driver().run(
            "campaigns",
            route(
                {
                    ACCOUNTS: [_accounts("1", "2", "3")],
                    CAMPAIGNS: [
                        _page(["c1", "c2"], has_next=True),
                        # `hasNext` on a page with no rows does not keep the walk going.
                        _page([], has_next=True),
                        _page(["c3"], has_next=False),
                        _page(["c4"], has_next=False),
                    ],
                }
            ),
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["c1", "c2", "c3", "c4"]
        campaign_requests = [request for request in result.requests if request.path.endswith(CAMPAIGNS)]
        assert [(request.param("adAccountId"), request.param("pageNo")) for request in campaign_requests] == [
            ("1", "1"),
            ("1", "2"),
            ("2", "1"),
            ("3", "1"),
        ]
        assert {request.param("pageSize") for request in campaign_requests} == {"500"}
        assert result.saved_states == [
            NewsBreakResumeConfig(account_id="1", page=2),
            NewsBreakResumeConfig(account_id="2", page=1),
            NewsBreakResumeConfig(account_id="3", page=1),
        ]

    @pytest.mark.parametrize(
        ("resume_state", "expected_requests"),
        [
            (NewsBreakResumeConfig(account_id="2", page=3), [("2", "3"), ("3", "1")]),
            # The saved account is gone, so the walk starts again from the first account.
            (NewsBreakResumeConfig(account_id="9", page=3), [("1", "1"), ("2", "1"), ("3", "1")]),
        ],
    )
    def test_resumes_from_saved_state(
        self, resume_state: NewsBreakResumeConfig, expected_requests: list[tuple[str, str]]
    ) -> None:
        result = _driver().run(
            "campaigns",
            route({ACCOUNTS: [_accounts("1", "2", "3")], CAMPAIGNS: [_page(["c"], has_next=False)] * 3}),
            resume_state=resume_state,
        )

        assert result.raised is None
        assert [
            (request.param("adAccountId"), request.param("pageNo"))
            for request in result.requests
            if request.path.endswith(CAMPAIGNS)
        ] == expected_requests


class TestReports:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self) -> Iterator[None]:
        with time_machine.travel(NOW, tick=False):
            yield

    @pytest.mark.parametrize(
        ("inputs", "expected_windows"),
        [
            # A full refresh reads from the creation of the account to today, in 7-day windows.
            (
                {"should_use_incremental_field": False},
                [("2024-03-01", "2024-03-07"), ("2024-03-08", "2024-03-14"), ("2024-03-15", "2024-03-16")],
            ),
            # An incremental run starts at the watermark the pipeline passes, already shifted by the lookback.
            (
                {"incremental_field": "date", "db_incremental_field_last_value": "2024-03-12"},
                [("2024-03-12", "2024-03-16")],
            ),
            # A watermark before the account existed does not read days before its creation.
            (
                {"incremental_field": "date", "db_incremental_field_last_value": "2023-01-01"},
                [("2024-03-01", "2024-03-07"), ("2024-03-08", "2024-03-14"), ("2024-03-15", "2024-03-16")],
            ),
        ],
    )
    def test_requests_date_windows(self, inputs: dict[str, Any], expected_windows: list[tuple[str, str]]) -> None:
        responses = [_report([{"date": "2024-03-01", "adAccountId": "123", "adId": "9", "cost": 5}])] + [
            _report([]) for _ in expected_windows[1:]
        ]
        result = _driver().run("ad_daily_report", route({ACCOUNTS: [_accounts("123")], REPORT: responses}), **inputs)

        assert result.raised is None
        bodies = _bodies(result.requests, REPORT)
        assert [(body["startDate"], body["endDate"]) for body in bodies] == expected_windows
        assert bodies[0] == {
            "name": "PostHog ad_daily_report",
            "timezone": "UTC",
            "dateRange": "FIXED",
            "startDate": expected_windows[0][0],
            "endDate": expected_windows[0][1],
            "filter": "AD_ACCOUNT",
            "filterIds": [123],
            "dimensions": ["DATE", "AD_ACCOUNT", "CAMPAIGN", "AD_SET", "AD"],
            "metrics": bodies[0]["metrics"],
        }
        assert {"COST", "IMPRESSION", "CLICK", "CONVERSION", "VALUE", "SALE_ROAS"} <= set(bodies[0]["metrics"])
        assert result.rows == [{"date": "2024-03-01", "adAccountId": "123", "adId": "9", "cost": 5}]
        assert result.response.primary_keys == ["date", "adAccountId", "campaignId", "adSetId", "adId"]
        assert result.response.sort_mode is None

    def test_report_dates_follow_the_report_time_zone(self) -> None:
        # At 2024-03-16 12:00 UTC it is already 2024-03-17 in Auckland.
        result = _driver(report_timezone="Pacific/Auckland").run(
            "ad_account_daily_report",
            route({ACCOUNTS: [_accounts("1")], REPORT: [_report([])]}),
            incremental_field="date",
            db_incremental_field_last_value="2024-03-15",
        )

        assert result.raised is None
        [body] = _bodies(result.requests, REPORT)
        assert (body["timezone"], body["startDate"], body["endDate"]) == (
            "Pacific/Auckland",
            "2024-03-15",
            "2024-03-17",
        )

    def test_rows_without_an_account_id_get_the_requested_account(self) -> None:
        result = _driver().run(
            "ad_account_daily_report",
            route({ACCOUNTS: [_accounts("7", created="")], REPORT: [_report([{"date": "2024-03-16", "cost": 1}])]}),
            incremental_field="date",
            db_incremental_field_last_value="2024-03-16",
        )

        assert result.raised is None
        assert result.rows == [{"date": "2024-03-16", "cost": 1, "adAccountId": "7"}]

    def test_saves_the_next_window_before_yielding_and_resumes_from_it(self) -> None:
        script = {ACCOUNTS: [_accounts("1", "2")], REPORT: [_report([{"date": "2024-03-15", "adAccountId": "1"}])] * 4}
        result = _driver().run(
            "ad_account_daily_report",
            route(script),
            resume_state=NewsBreakResumeConfig(account_id="1", window_start="2024-03-15"),
        )

        assert result.raised is None
        assert [(body["filterIds"], body["startDate"]) for body in _bodies(result.requests, REPORT)] == [
            ([1], "2024-03-15"),
            ([2], "2024-03-01"),
            ([2], "2024-03-08"),
            ([2], "2024-03-15"),
        ]
        assert result.saved_states == [
            NewsBreakResumeConfig(account_id="2"),
            NewsBreakResumeConfig(account_id="2", window_start="2024-03-08"),
            NewsBreakResumeConfig(account_id="2", window_start="2024-03-15"),
        ]
        assert result.committed_states == result.saved_states


class TestErrors:
    @pytest.mark.parametrize(
        ("answer", "expected"),
        [
            (ScriptedResponse(json={"code": 4033, "errMsg": "Invalid access token"}), INVALID_TOKEN_ERROR),
            (ScriptedResponse(json={"code": 4031, "errMsg": "Not login"}), INVALID_TOKEN_ERROR),
            (ScriptedResponse(status=401, json={}), INVALID_TOKEN_ERROR),
            (ScriptedResponse(json={"code": 403, "errMsg": "Permission denied"}), PERMISSION_ERROR),
            (
                ScriptedResponse(json={"code": -1, "errMsg": "Unknown error"}),
                "NewsBreak API error -1 for /ad-account/getGroupsByOrgIds: Unknown error",
            ),
            (ScriptedResponse(json={"code": 4034, "errMsg": "Rate limit exceeded"}), "NewsBreak rate limit reached"),
            (ScriptedResponse(status=503, json={}), "NewsBreak returned HTTP 503"),
        ],
    )
    def test_maps_vendor_errors(self, answer: ScriptedResponse, expected: str) -> None:
        result = _driver().run("campaigns", always(answer))

        assert result.raised is not None
        assert str(result.raised).startswith(expected)

    def test_invalid_time_zone_fails_before_any_request(self) -> None:
        result = _driver(report_timezone="Mars/Olympus").run("ad_daily_report", always(_ok({})))

        assert str(result.raised) == INVALID_TIMEZONE_ERROR
        assert result.requests == []


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("org_ids", "report_timezone", "answer", "expected"),
        [
            ("10", None, _accounts("1"), (True, None)),
            # The sync reports an empty organization list, so the probe accepts the token.
            (None, None, _ok({"list": []}), (True, None)),
            (
                "10",
                None,
                ScriptedResponse(json={"code": 4033, "errMsg": "Invalid access token"}),
                (False, INVALID_TOKEN_ERROR),
            ),
            # The probe does not retry, so the form answers at once.
            ("10", None, ScriptedResponse(status=502, json={}), (False, UNREACHABLE_ERROR)),
            ("10", "Not/AZone", _accounts("1"), (False, INVALID_TIMEZONE_ERROR)),
        ],
    )
    def test_validate_credentials(
        self,
        org_ids: str | None,
        report_timezone: str | None,
        answer: ScriptedResponse,
        expected: tuple[bool, str | None],
    ) -> None:
        with scripted_network(always(answer)) as network:
            assert validate_credentials("nb_token", org_ids, report_timezone) == expected

        assert [request.path.removeprefix("/business-api/v1") for request in network.requests_log] == (
            [] if report_timezone else [ACCOUNTS if org_ids else ADMIN_ORGS]
        )
