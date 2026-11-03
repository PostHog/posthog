from datetime import date
from typing import Any

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized
from requests.exceptions import HTTPError

from products.warehouse_sources.sources.rokt_ads.rokt_ads import (
    DateWindow,
    ReportCapabilities,
    RoktAdsClient,
    RoktAdsError,
    RoktAdsResumeConfig,
    _date_windows,
    build_discovery_body,
    build_report_body,
    resolve_start_date,
    rokt_ads_metadata_rows,
    rokt_ads_source,
)
from products.warehouse_sources.sources.rokt_ads.settings import (
    CAMPAIGN_METRICS,
    ENDPOINTS,
    INITIAL_BACKFILL_DAYS,
    METADATA_ENDPOINTS,
)

ALL_DIMENSIONS = {dimension for endpoint in ENDPOINTS.values() for dimension in endpoint["dimensions"]} | {
    dimension for endpoint in METADATA_ENDPOINTS.values() for dimension in endpoint["discovery_dimensions"]
}
ALL_METRICS = set(CAMPAIGN_METRICS)
ALL_CAPABILITIES = ReportCapabilities(dimensions=ALL_DIMENSIONS, metrics=ALL_METRICS)
MARCH_WINDOW = DateWindow(start=date(2026, 3, 1), end=date(2026, 4, 1))


def _manager(resume_state: RoktAdsResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


class TestDateWindows:
    def test_windows_never_overlap_or_leave_gaps(self):
        windows = list(_date_windows(date(2026, 1, 1), date(2026, 6, 1), 31))
        for earlier, later in zip(windows, windows[1:]):
            assert earlier.end == later.start


class TestResolveStartDate:
    def test_no_cursor_falls_back_to_the_backfill_window(self):
        today = date(2026, 8, 13)
        resolved = resolve_start_date(None, today)
        assert (today - resolved).days == INITIAL_BACKFILL_DAYS

    @parameterized.expand(
        ["2026-03-04T00:00:00Z", "2026-03-04T00:00:00+00:00", "2026-03-04"],
    )
    def test_parses_the_timestamp_shapes_the_report_returns(self, cursor: str):
        assert resolve_start_date(cursor, date(2026, 8, 13)) == date(2026, 3, 4)

    def test_blank_cursor_falls_back(self):
        today = date(2026, 8, 13)
        assert (today - resolve_start_date("", today)).days == INITIAL_BACKFILL_DAYS


class TestBuildReportBody:
    def test_drops_metrics_the_account_cannot_report_on(self):
        body = build_report_body(
            "CampaignPerformance",
            MARCH_WINDOW,
            ReportCapabilities(dimensions=ALL_DIMENSIONS, metrics={"impressions", "referrals"}),
            None,
            None,
        )
        assert body["metrics"] == ["impressions", "referrals"]

    def test_rejects_a_missing_dimension_rather_than_collapsing_the_grain(self):
        allowed = ALL_DIMENSIONS - {"creative_id"}
        with pytest.raises(RoktAdsError, match="creative_id"):
            build_report_body(
                "CreativePerformance",
                MARCH_WINDOW,
                ReportCapabilities(dimensions=allowed, metrics=ALL_METRICS),
                None,
                None,
            )

    def test_rejects_an_account_that_grants_no_metrics(self):
        with pytest.raises(RoktAdsError, match="none of the metrics"):
            build_report_body(
                "CampaignPerformance",
                MARCH_WINDOW,
                ReportCapabilities(dimensions=ALL_DIMENSIONS, metrics=set()),
                None,
                None,
            )

    def test_passes_optional_settings_through(self):
        body = build_report_body(
            "CampaignPerformance",
            MARCH_WINDOW,
            ALL_CAPABILITIES,
            "Australia/Sydney",
            "AUD",
        )
        assert body["timezoneVariation"] == "Australia/Sydney"
        assert body["currencyCode"] == "AUD"


class TestRoktAdsSource:
    def _client(self, rows: list[dict[str, Any]] | None = None) -> MagicMock:
        client = MagicMock()
        client.report_capabilities.return_value = ALL_CAPABILITIES
        client.run_report.return_value = rows if rows is not None else [{"datetime": "2026-03-04T00:00:00Z"}]
        return client

    def test_accounts_endpoint_yields_the_account_list_and_runs_no_report(self):
        client = MagicMock()
        client.list_accounts.return_value = [{"accountId": "acc_1"}]

        batches = list(rokt_ads_source(client, "acc_1", "Accounts", _manager(), None, today=date(2026, 8, 13)))

        assert batches == [[{"accountId": "acc_1"}]]
        client.run_report.assert_not_called()

    @parameterized.expand([("configured", "GBP"), ("default", None)])
    def test_each_report_row_keeps_the_currency_used_for_its_sync(self, _name: str, currency: str | None) -> None:
        client = self._client(rows=[{"datetime": "2026-08-13T00:00:00Z", "gross_cost": 12.5}])
        historical = list(
            rokt_ads_source(
                client,
                "acc_1",
                "CampaignPerformance",
                _manager(),
                "2026-08-13",
                currency_code=currency,
                today=date(2026, 8, 13),
            )
        )
        current = list(
            rokt_ads_source(
                client,
                "acc_1",
                "CampaignPerformance",
                _manager(),
                "2026-08-14",
                currency_code="AUD",
                today=date(2026, 8, 14),
            )
        )
        assert historical[0][0]["currency_code"] == (currency or "USD")
        assert current[0][0]["currency_code"] == "AUD"
        assert historical[0][0]["gross_cost"] == 12.5

    def test_saved_resume_state_wins_over_the_incremental_cursor(self):
        client = self._client()
        manager = _manager(RoktAdsResumeConfig(next_start_date="2026-08-10"))

        list(rokt_ads_source(client, "acc_1", "CampaignPerformance", manager, "2026-01-01", today=date(2026, 8, 13)))

        assert client.run_report.call_args_list[0].args[2]["startDate"] == "2026-08-10"


class TestBuildDiscoveryBody:
    def test_asks_for_one_row_per_id_and_not_one_per_day(self):
        body = build_discovery_body(
            "CreativeMetadata",
            MARCH_WINDOW,
            ReportCapabilities(dimensions=ALL_DIMENSIONS, metrics={"referrals", "gross_cost"}),
        )
        assert "interval" not in body
        assert body["dimensions"] == ["campaign_id", "creative_id"]
        assert body["metrics"] == ["referrals"]


class TestRoktAdsMetadataRows:
    TODAY = date(2026, 8, 13)

    def _client(self, report_rows_per_window: list[list[dict[str, Any]]], metadata: Any = None) -> MagicMock:
        client = MagicMock()
        client.report_capabilities.return_value = ALL_CAPABILITIES
        windows = list(_date_windows(date(2024, 8, 13), date(2026, 8, 14), 31))
        responses = report_rows_per_window + [[] for _ in range(len(windows) - len(report_rows_per_window))]
        client.run_report.side_effect = responses
        client.get_metadata.side_effect = metadata or (lambda path: {"path": path, "status": "Active"})
        return client

    @parameterized.expand(
        [
            (
                "CampaignMetadata",
                [[{"campaign_id": "c1"}, {"campaign_id": "c2"}], [{"campaign_id": "c1"}, {"campaign_id": "c3"}]],
                [
                    ("/metadata/accounts/acc_1/campaigns/c1", {"campaignId": "c1"}),
                    ("/metadata/accounts/acc_1/campaigns/c2", {"campaignId": "c2"}),
                    ("/metadata/accounts/acc_1/campaigns/c3", {"campaignId": "c3"}),
                ],
            ),
            (
                "CreativeMetadata",
                # The same creative ID under two campaigns is two rows.
                [[{"campaign_id": "c1", "creative_id": "k1"}], [{"campaign_id": "c2", "creative_id": "k1"}]],
                [
                    ("/metadata/accounts/acc_1/campaigns/c1/creatives/k1", {"campaignId": "c1", "creativeId": "k1"}),
                    ("/metadata/accounts/acc_1/campaigns/c2/creatives/k1", {"campaignId": "c2", "creativeId": "k1"}),
                ],
            ),
            (
                "AudienceMetadata",
                [[{"campaign_id": "c1", "audience_id": "a1"}, {"campaign_id": "c1", "audience_id": None}]],
                [("/metadata/accounts/acc_1/campaigns/c1/audiences/a1", {"campaignId": "c1", "audienceId": "a1"})],
            ),
        ]
    )
    def test_reads_each_discovered_id_once(self, endpoint_name, report_rows_per_window, expected):
        client = self._client(report_rows_per_window)

        rows = list(rokt_ads_metadata_rows(client, "acc_1", endpoint_name, _manager(), today=self.TODAY))

        assert [call.args[0] for call in client.get_metadata.call_args_list] == [path for path, _ in expected]
        assert rows == [{"path": path, "status": "Active", **ids} for path, ids in expected]

    def test_discovery_walks_the_whole_backfill_range_in_order(self):
        client = self._client([])

        list(rokt_ads_metadata_rows(client, "acc_1", "CampaignMetadata", _manager(), today=self.TODAY))

        bodies = [call.args[2] for call in client.run_report.call_args_list]
        assert bodies[0]["startDate"] == "2024-08-13"
        assert bodies[-1]["endDate"] == "2026-08-14"
        assert all(call.args[1] == "campaigns" for call in client.run_report.call_args_list)

    def test_path_ids_win_over_a_missing_or_different_response_field(self):
        client = self._client(
            [[{"campaign_id": "c1", "creative_id": "k1"}]],
            metadata=lambda path: {"campaignId": None, "name": "Spring sale"},
        )

        rows = list(rokt_ads_metadata_rows(client, "acc_1", "CreativeMetadata", _manager(), today=self.TODAY))

        assert rows == [{"campaignId": "c1", "creativeId": "k1", "name": "Spring sale"}]

    def test_skips_an_id_rokt_no_longer_has_and_reaches_a_safe_point(self):
        client = self._client(
            [[{"campaign_id": "gone"}, {"campaign_id": "c2"}]],
            metadata=lambda path: None if path.endswith("/gone") else {"status": "Active"},
        )
        manager = _manager()

        rows = list(rokt_ads_metadata_rows(client, "acc_1", "CampaignMetadata", manager, today=self.TODAY))

        assert rows == [{"status": "Active", "campaignId": "c2"}]
        # One safe point per discovery window, plus one for the skipped ID.
        assert manager.safe_point.call_count == client.run_report.call_count + 1
        manager.save_state.assert_not_called()


class TestRoktAdsClient:
    def _client(self, token_session: MagicMock, session: MagicMock) -> RoktAdsClient:
        return RoktAdsClient("app-id", "app-secret", session=session, token_session=token_session)

    def _token_response(self, expires_in: int = 3600) -> MagicMock:
        response = MagicMock()
        response.json.return_value = {"access_token": "tok", "expires_in": expires_in, "token_type": "Bearer"}
        return response

    def test_token_response_without_a_token_raises(self):
        token_session = MagicMock()
        response = MagicMock()
        response.json.return_value = {"expires_in": 3600}
        token_session.post.return_value = response

        with pytest.raises(RoktAdsError, match="no access_token"):
            self._client(token_session, MagicMock()).access_token()

    def test_report_capabilities_reduces_help_payloads_to_slug_sets(self):
        token_session = MagicMock()
        token_session.post.return_value = self._token_response()
        session = MagicMock()
        response = MagicMock()
        response.json.return_value = {
            "dimensions": [{"slug": "campaign_id", "description": "x"}],
            "metrics": [{"slug": "impressions", "description": "y"}, {"description": "no slug"}],
        }
        session.get.return_value = response

        capabilities = self._client(token_session, session).report_capabilities("acc_1", "campaigns")

        assert capabilities.dimensions == {"campaign_id"}
        assert capabilities.metrics == {"impressions"}

    def test_run_report_routes_each_kind_to_its_own_path(self):
        token_session = MagicMock()
        token_session.post.return_value = self._token_response()
        session = MagicMock()
        response = MagicMock()
        response.json.return_value = {"data": [{"datetime": "2026-03-04T00:00:00Z"}]}
        session.post.return_value = response
        client = self._client(token_session, session)

        client.run_report("acc_1", "campaigns", {})
        client.run_report("acc_1", "transactions", {})

        paths = [call.args[0] for call in session.post.call_args_list]
        assert paths == [
            "https://api.rokt.com/v1/query/accounts/acc_1/campaigns/",
            "https://api.rokt.com/v1/query/accounts/acc_1/transactions",
        ]

    def _error_response(self, body: Any = None, text: str = "") -> MagicMock:
        response = MagicMock()
        url = "https://api.rokt.com/v1/query/accounts/acc_1/campaigns/"
        response.raise_for_status.side_effect = HTTPError(
            f"400 Client Error: Bad Request for url: {url}", response=response
        )
        if body is None:
            response.json.side_effect = ValueError
            response.text = text
        else:
            response.json.return_value = body
        return response

    @parameterized.expand(
        [
            ({"message": "endDate cannot be in the future"}, "endDate cannot be in the future"),
            ({"error": "unknown column datetime"}, "unknown column datetime"),
            (None, "plain text failure"),
        ]
    )
    def test_post_error_keeps_the_status_line_and_adds_rokts_explanation(self, body, expected_detail):
        token_session = MagicMock()
        token_session.post.return_value = self._token_response()
        session = MagicMock()
        session.post.return_value = self._error_response(body=body, text=expected_detail)

        with pytest.raises(RoktAdsError) as exc:
            self._client(token_session, session).post("/v1/query/accounts/acc_1/campaigns/", {})

        message = str(exc.value)
        # The status line lets get_non_retryable_errors classify this as permanent.
        assert "400 Client Error" in message
        assert expected_detail in message

    def _metadata_client(self, status: int) -> RoktAdsClient:
        token_session = MagicMock()
        token_session.post.return_value = self._token_response()
        session = MagicMock()
        response = MagicMock()
        response.status_code = status
        response.json.return_value = {"message": "not found"} if status >= 400 else {"campaignId": "c1"}
        if status >= 400:
            response.raise_for_status.side_effect = HTTPError(f"{status} error", response=response)
        session.get.return_value = response
        return self._client(token_session, session)

    @parameterized.expand([(200, {"campaignId": "c1"}), (404, None)])
    def test_get_metadata_returns_the_object_or_none_when_it_is_gone(self, status: int, expected: Any):
        assert self._metadata_client(status).get_metadata("/metadata/accounts/acc_1/campaigns/c1") == expected

    @parameterized.expand([(401,), (403,), (500,)])
    def test_get_metadata_raises_every_other_error(self, status: int):
        with pytest.raises(RoktAdsError, match=str(status)):
            self._metadata_client(status).get_metadata("/metadata/accounts/acc_1/campaigns/c1")
