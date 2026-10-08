from datetime import date
from typing import Any

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.rokt_ads.rokt_ads import (
    DateWindow,
    ReportCapabilities,
    RoktAdsClient,
    RoktAdsError,
    RoktAdsResumeConfig,
    _date_windows,
    build_report_body,
    resolve_start_date,
    rokt_ads_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rokt_ads.settings import (
    CAMPAIGN_METRICS,
    ENDPOINTS,
    INITIAL_BACKFILL_DAYS,
)

ALL_DIMENSIONS = {dimension for endpoint in ENDPOINTS.values() for dimension in endpoint["dimensions"]}
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
