import json
import datetime as dt
from typing import Any, Optional, cast

import pytest
from freezegun import freeze_time
from unittest import mock

import requests
import structlog
from tenacity import wait_none

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_explorer import aws_cost_explorer
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_explorer.aws_cost_explorer import (
    AwsCostExplorerError,
    AwsCostExplorerResumeConfig,
    AwsCostExplorerThrottledError,
    build_payload,
    build_windows,
    error_for_response,
    get_rows,
    normalize_results,
    resolve_start_date,
    send_operation,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_explorer.settings import (
    AWS_COST_EXPLORER_ENDPOINTS,
    CE_ENDPOINT_URL,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

LOGGER = structlog.get_logger()

COST_DAILY = AWS_COST_EXPLORER_ENDPOINTS["cost_and_usage_daily"]
RESERVATION = AWS_COST_EXPLORER_ENDPOINTS["reservation_utilization_daily"]
SAVINGS_PLANS = AWS_COST_EXPLORER_ENDPOINTS["savings_plans_utilization_daily"]


def without_retry_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the throttling retry's behaviour but drop its wait, so tests stay fast."""
    monkeypatch.setattr(cast(Any, send_operation).retry, "wait", wait_none())


class FakeResumeManager(ResumableSourceManager[AwsCostExplorerResumeConfig]):
    def __init__(self, state: Optional[AwsCostExplorerResumeConfig] = None) -> None:
        self.state = state
        self.saved: list[AwsCostExplorerResumeConfig] = []
        self.cleared = False

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[AwsCostExplorerResumeConfig]:
        return self.state

    def save_state(self, data: AwsCostExplorerResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared = True


def make_response(
    status_code: int, payload: Optional[dict[str, Any]] = None, headers: Optional[dict[str, str]] = None
) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.headers.update(headers or {})
    response._content = json.dumps(payload if payload is not None else {}).encode()
    return response


def cost_page(groups: list[dict[str, Any]], next_page_token: Optional[str] = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": "2024-03-01", "End": "2024-03-02"},
                "Estimated": False,
                "Groups": groups,
                "Total": {},
            }
        ]
    }
    if next_page_token is not None:
        body["NextPageToken"] = next_page_token
    return body


class TestWindows:
    @pytest.mark.parametrize(
        "start,end,window_days,expected",
        [
            # Exclusive end: the final window stops exactly on `end`.
            (
                "2024-01-01",
                "2024-01-11",
                4,
                [("2024-01-01", "2024-01-05"), ("2024-01-05", "2024-01-09"), ("2024-01-09", "2024-01-11")],
            ),
            ("2024-01-01", "2024-01-05", 4, [("2024-01-01", "2024-01-05")]),
            ("2024-01-01", "2024-01-02", 92, [("2024-01-01", "2024-01-02")]),
            # A start on or past the end asks AWS for nothing at all.
            ("2024-01-05", "2024-01-05", 92, []),
            ("2024-01-06", "2024-01-05", 92, []),
        ],
    )
    def test_windows_tile_the_range_without_gaps_or_overlap(
        self, start: str, end: str, window_days: int, expected: list[tuple[str, str]]
    ) -> None:
        windows = build_windows(dt.date.fromisoformat(start), dt.date.fromisoformat(end), window_days)

        assert [(w.start.isoformat(), w.end.isoformat()) for w in windows] == expected


class TestResolveStartDate:
    END = dt.date(2024, 6, 1)

    def test_defaults_to_a_year_back_when_no_start_date_is_configured(self) -> None:
        assert resolve_start_date(None, COST_DAILY, False, None, self.END) == dt.date(2023, 6, 2)

    @pytest.mark.parametrize("configured", ["2024-01-01", "2024-01-01T00:00:00Z"])
    def test_uses_the_configured_start_date_on_a_full_refresh(self, configured: str) -> None:
        assert resolve_start_date(configured, COST_DAILY, False, None, self.END) == dt.date(2024, 1, 1)

    @pytest.mark.parametrize(
        "watermark",
        [
            "2024-05-20",
            dt.date(2024, 5, 20),
            dt.datetime(2024, 5, 20, 13, 45, tzinfo=dt.UTC),
        ],
    )
    def test_incremental_rewinds_behind_the_watermark_to_re_read_restated_periods(self, watermark: Any) -> None:
        # AWS keeps restating recent periods, so the window has to reach back behind the cursor.
        assert resolve_start_date("2024-01-01", COST_DAILY, True, watermark, self.END) == dt.date(2024, 5, 13)

    def test_incremental_never_reaches_before_the_configured_start_date(self) -> None:
        assert resolve_start_date("2024-05-15", COST_DAILY, True, "2024-05-16", self.END) == dt.date(2024, 5, 15)

    def test_monthly_rewinds_further_than_daily(self) -> None:
        monthly = AWS_COST_EXPLORER_ENDPOINTS["cost_and_usage_monthly"]

        assert resolve_start_date("2023-01-01", monthly, True, "2024-05-20", self.END) == dt.date(2024, 4, 5)

    def test_a_watermark_past_the_end_is_clamped_so_no_window_is_requested(self) -> None:
        assert resolve_start_date("2024-01-01", COST_DAILY, True, "2025-01-01", self.END) == self.END

    def test_ignores_an_unparseable_watermark(self) -> None:
        assert resolve_start_date("2024-01-01", COST_DAILY, True, "not-a-date", self.END) == dt.date(2024, 1, 1)


class TestBuildPayload:
    WINDOW = aws_cost_explorer.TimeWindow(start=dt.date(2024, 3, 1), end=dt.date(2024, 4, 1))

    def test_cost_payload_carries_the_time_window_metrics_and_group_by(self) -> None:
        payload = build_payload(COST_DAILY, self.WINDOW, None)

        assert payload["TimePeriod"] == {"Start": "2024-03-01", "End": "2024-04-01"}
        assert payload["Granularity"] == "DAILY"
        assert payload["Metrics"] == list(COST_DAILY.metrics)
        assert payload["GroupBy"] == [
            {"Type": "DIMENSION", "Key": "SERVICE"},
            {"Type": "DIMENSION", "Key": "LINKED_ACCOUNT"},
        ]
        assert "NextPageToken" not in payload

    def test_page_token_is_sent_under_the_endpoints_own_key(self) -> None:
        assert build_payload(COST_DAILY, self.WINDOW, "tok")["NextPageToken"] == "tok"

    def test_endpoints_without_metrics_or_grouping_send_neither(self) -> None:
        payload = build_payload(RESERVATION, self.WINDOW, None)

        assert "Metrics" not in payload
        assert "GroupBy" not in payload

    def test_a_token_is_never_sent_to_an_operation_that_cannot_paginate(self) -> None:
        # GetSavingsPlansUtilization has no pagination; sending a token would be rejected.
        assert build_payload(SAVINGS_PLANS, self.WINDOW, "tok") == {
            "TimePeriod": {"Start": "2024-03-01", "End": "2024-04-01"},
            "Granularity": "DAILY",
        }


class TestNormalizeResults:
    def test_grouped_costs_fan_out_one_row_per_group_with_dimensions_mapped_in_order(self) -> None:
        rows = normalize_results(
            COST_DAILY,
            cost_page(
                [
                    {
                        "Keys": ["Amazon Elastic Compute Cloud - Compute", "123456789012"],
                        "Metrics": {
                            "UnblendedCost": {"Amount": "12.5", "Unit": "USD"},
                            "UsageQuantity": {"Amount": "3", "Unit": "Hrs"},
                        },
                    },
                    {
                        "Keys": ["AmazonS3", "210987654321"],
                        "Metrics": {"UnblendedCost": {"Amount": "0.4", "Unit": "USD"}},
                    },
                ]
            ),
        )

        assert len(rows) == 2
        assert rows[0]["period_start"] == dt.datetime(2024, 3, 1, tzinfo=dt.UTC)
        assert rows[0]["period_end"] == dt.datetime(2024, 3, 2, tzinfo=dt.UTC)
        assert rows[0]["granularity"] == "DAILY"
        assert rows[0]["estimated"] is False
        assert rows[0]["service"] == "Amazon Elastic Compute Cloud - Compute"
        assert rows[0]["linked_account"] == "123456789012"
        assert rows[0]["unblended_cost_amount"] == 12.5
        assert rows[0]["unblended_cost_unit"] == "USD"
        assert rows[0]["usage_quantity_amount"] == 3.0
        assert rows[1]["service"] == "AmazonS3"
        assert rows[1]["linked_account"] == "210987654321"

    def test_every_configured_metric_gets_a_column_even_when_aws_omits_it(self) -> None:
        # Otherwise the Arrow schema would shift between pages depending on which metrics AWS returned.
        rows = normalize_results(
            COST_DAILY,
            cost_page([{"Keys": ["AmazonS3", "1"], "Metrics": {"UnblendedCost": {"Amount": "1", "Unit": "USD"}}}]),
        )

        for metric_column in ("amortized_cost", "blended_cost", "net_amortized_cost", "net_unblended_cost"):
            assert rows[0][f"{metric_column}_amount"] is None
            assert rows[0][f"{metric_column}_unit"] is None

    def test_an_ungrouped_period_falls_back_to_the_period_total(self) -> None:
        rows = normalize_results(
            COST_DAILY,
            {
                "ResultsByTime": [
                    {
                        "TimePeriod": {"Start": "2024-03-01", "End": "2024-03-02"},
                        "Estimated": True,
                        "Groups": [],
                        "Total": {"UnblendedCost": {"Amount": "9.75", "Unit": "USD"}},
                    }
                ]
            },
        )

        assert len(rows) == 1
        assert rows[0]["service"] is None
        assert rows[0]["linked_account"] is None
        assert rows[0]["estimated"] is True
        assert rows[0]["unblended_cost_amount"] == 9.75
        assert rows[0]["unblended_cost_unit"] == "USD"

    def test_reservation_totals_are_flattened_into_snake_cased_columns(self) -> None:
        rows = normalize_results(
            RESERVATION,
            {
                "UtilizationsByTime": [
                    {
                        "TimePeriod": {"Start": "2024-03-01", "End": "2024-03-02"},
                        "Total": {
                            "UtilizationPercentage": "97.5",
                            "NetRISavings": "120.25",
                            "OnDemandCostOfRIHoursUsed": "400",
                            "RICostForUnusedHours": "1.5",
                        },
                    }
                ]
            },
        )

        assert rows[0]["utilization_percentage"] == 97.5
        assert rows[0]["net_ri_savings"] == 120.25
        assert rows[0]["on_demand_cost_of_ri_hours_used"] == 400.0
        assert rows[0]["ri_cost_for_unused_hours"] == 1.5

    def test_savings_plans_sub_structures_flatten_into_non_colliding_columns(self) -> None:
        rows = normalize_results(
            SAVINGS_PLANS,
            {
                "SavingsPlansUtilizationsByTime": [
                    {
                        "TimePeriod": {"Start": "2024-03-01", "End": "2024-03-02"},
                        "Utilization": {"TotalCommitment": "100", "UtilizationPercentage": "88"},
                        "Savings": {"NetSavings": "12"},
                        "AmortizedCommitment": {"TotalAmortizedCommitment": "100"},
                    }
                ]
            },
        )

        assert rows[0]["total_commitment"] == 100.0
        assert rows[0]["utilization_percentage"] == 88.0
        assert rows[0]["savings_net_savings"] == 12.0
        assert rows[0]["amortized_commitment_total_amortized_commitment"] == 100.0

    def test_an_empty_response_yields_no_rows(self) -> None:
        assert normalize_results(COST_DAILY, {}) == []


class TestErrorClassification:
    @pytest.mark.parametrize(
        "code",
        ["LimitExceededException", "ThrottlingException", "TooManyRequestsException", "RequestLimitExceeded"],
    )
    def test_throttling_codes_are_retryable(self, code: str) -> None:
        response = make_response(400, {"__type": f"com.amazon.coral.availability#{code}", "message": "slow down"})

        error = error_for_response(response)

        assert isinstance(error, AwsCostExplorerThrottledError)
        assert f"AWS Cost Explorer request failed: {code}" in str(error)

    @pytest.mark.parametrize(
        "code",
        ["AccessDeniedException", "UnrecognizedClientException", "ExpiredTokenException", "DataUnavailableException"],
    )
    def test_permanent_codes_are_not_retryable_and_stringify_for_the_source_mapping(self, code: str) -> None:
        response = make_response(400, {"__type": code, "message": "nope"})

        error = error_for_response(response)

        assert not isinstance(error, AwsCostExplorerThrottledError)
        assert str(error) == f"AWS Cost Explorer request failed: {code} - nope"

    def test_the_error_type_header_wins_over_the_body(self) -> None:
        response = make_response(
            400,
            {"message": "nope"},
            headers={"x-amzn-ErrorType": "AccessDeniedException:http://internal.amazon.com/coral/"},
        )

        assert str(error_for_response(response)).startswith(
            "AWS Cost Explorer request failed: AccessDeniedException - nope"
        )

    def test_a_non_json_error_body_still_produces_a_usable_message(self) -> None:
        response = requests.Response()
        response.status_code = 503
        response._content = b"<html>gateway</html>"

        error = error_for_response(response)

        assert not isinstance(error, AwsCostExplorerThrottledError)
        assert "HTTP 503" in str(error)


class TestSendOperation:
    def test_requests_are_sigv4_signed_and_dispatched_via_x_amz_target(self) -> None:
        session = mock.MagicMock(spec=requests.Session)
        session.post.return_value = make_response(200, {"ResultsByTime": []})
        credentials = aws_cost_explorer.Credentials("AKIAEXAMPLE", "secret")

        with freeze_time("2024-03-05T10:00:00Z"):
            send_operation(session, credentials, "GetCostAndUsage", {"Granularity": "DAILY"})

        _, kwargs = session.post.call_args
        assert session.post.call_args[0][0] == CE_ENDPOINT_URL
        assert kwargs["headers"]["X-Amz-Target"] == "AWSInsightsIndexService.GetCostAndUsage"
        assert kwargs["headers"]["Content-Type"] == "application/x-amz-json-1.1"
        assert kwargs["headers"]["X-Amz-Date"] == "20240305T100000Z"
        assert kwargs["headers"]["Authorization"].startswith(
            "AWS4-HMAC-SHA256 Credential=AKIAEXAMPLE/20240305/us-east-1/ce/aws4_request"
        )
        assert json.loads(kwargs["data"]) == {"Granularity": "DAILY"}

    def test_temporary_credentials_carry_the_session_token(self) -> None:
        session = mock.MagicMock(spec=requests.Session)
        session.post.return_value = make_response(200, {})
        credentials = aws_cost_explorer.Credentials("AKIAEXAMPLE", "secret", "session-token")

        send_operation(session, credentials, "GetCostAndUsage", {})

        assert session.post.call_args[1]["headers"]["X-Amz-Security-Token"] == "session-token"

    def test_throttled_calls_are_retried_until_they_succeed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        without_retry_backoff(monkeypatch)
        session = mock.MagicMock(spec=requests.Session)
        session.post.side_effect = [
            make_response(400, {"__type": "LimitExceededException", "message": "slow down"}),
            make_response(200, {"ResultsByTime": []}),
        ]

        body = send_operation(session, aws_cost_explorer.Credentials("k", "s"), "GetCostAndUsage", {})

        assert body == {"ResultsByTime": []}
        assert session.post.call_count == 2

    def test_permanent_errors_are_raised_without_retrying(self, monkeypatch: pytest.MonkeyPatch) -> None:
        without_retry_backoff(monkeypatch)
        session = mock.MagicMock(spec=requests.Session)
        session.post.return_value = make_response(400, {"__type": "AccessDeniedException", "message": "denied"})

        with pytest.raises(AwsCostExplorerError):
            send_operation(session, aws_cost_explorer.Credentials("k", "s"), "GetCostAndUsage", {})

        assert session.post.call_count == 1


class TestValidateCredentials:
    def test_missing_credentials_short_circuit_without_a_billed_request(self) -> None:
        with mock.patch.object(aws_cost_explorer, "send_operation") as send:
            assert validate_credentials("", "secret", None) == (
                False,
                "AWS access key ID and secret access key are required",
            )

        send.assert_not_called()

    def test_a_successful_probe_validates(self) -> None:
        with mock.patch.object(aws_cost_explorer, "send_operation", return_value={"ResultsByTime": []}) as send:
            assert validate_credentials("key", "secret", None) == (True, None)

        assert send.call_args[0][2] == "GetCostAndUsage"

    def test_an_api_error_is_surfaced_to_the_user(self) -> None:
        error = AwsCostExplorerError("AWS Cost Explorer request failed: AccessDeniedException - denied")

        with mock.patch.object(aws_cost_explorer, "send_operation", side_effect=error):
            assert validate_credentials("key", "secret", None) == (False, str(error))

    def test_a_transport_failure_does_not_leak_internals(self) -> None:
        with mock.patch.object(aws_cost_explorer, "send_operation", side_effect=requests.ConnectionError("boom")):
            assert validate_credentials("key", "secret", None) == (
                False,
                "Could not reach the AWS Cost Explorer API",
            )


@freeze_time("2024-03-03T12:00:00Z")
class TestGetRows:
    def _run(
        self,
        responses: list[dict[str, Any]],
        manager: FakeResumeManager,
        endpoint: str = "cost_and_usage_daily",
        start_date: Optional[str] = "2024-03-01",
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[list[dict[str, Any]]], mock.MagicMock]:
        with mock.patch.object(aws_cost_explorer, "send_operation", side_effect=responses) as send:
            batches = list(
                get_rows(
                    aws_access_key_id="key",
                    aws_secret_access_key="secret",
                    aws_session_token=None,
                    start_date=start_date,
                    endpoint=endpoint,
                    resumable_source_manager=manager,
                    should_use_incremental_field=should_use_incremental_field,
                    db_incremental_field_last_value=db_incremental_field_last_value,
                    logger=LOGGER,
                )
            )
        return batches, send

    def test_pagination_stops_when_aws_stops_returning_a_token(self) -> None:
        manager = FakeResumeManager()

        batches, send = self._run(
            [
                cost_page([{"Keys": ["AmazonS3", "1"], "Metrics": {}}], next_page_token="page-2"),
                cost_page([{"Keys": ["AmazonEC2", "1"], "Metrics": {}}]),
            ],
            manager,
        )

        assert send.call_count == 2
        assert [row["service"] for batch in batches for row in batch] == ["AmazonS3", "AmazonEC2"]
        assert send.call_args_list[0][0][3].get("NextPageToken") is None
        assert send.call_args_list[1][0][3]["NextPageToken"] == "page-2"

    def test_state_is_saved_after_each_page_and_cleared_once_the_range_is_walked(self) -> None:
        manager = FakeResumeManager()

        self._run(
            [
                cost_page([{"Keys": ["AmazonS3", "1"], "Metrics": {}}], next_page_token="page-2"),
                cost_page([{"Keys": ["AmazonEC2", "1"], "Metrics": {}}]),
            ],
            manager,
        )

        assert manager.saved == [
            AwsCostExplorerResumeConfig(window_start="2024-03-01", next_page_token="page-2"),
            AwsCostExplorerResumeConfig(window_start="2024-03-01", next_page_token=None),
        ]
        assert manager.cleared is True

    def test_a_saved_state_resumes_the_same_window_at_the_saved_page(self) -> None:
        manager = FakeResumeManager(AwsCostExplorerResumeConfig(window_start="2024-03-01", next_page_token="page-7"))

        _, send = self._run([cost_page([{"Keys": ["AmazonS3", "1"], "Metrics": {}}])], manager)

        assert send.call_count == 1
        assert send.call_args_list[0][0][3]["NextPageToken"] == "page-7"

    def test_a_stale_saved_window_restarts_the_range_rather_than_skipping_data(self) -> None:
        # The window list shifts whenever the incremental watermark moves, so a token from a
        # window that no longer exists must not silently skip the windows before it.
        manager = FakeResumeManager(AwsCostExplorerResumeConfig(window_start="2019-01-01", next_page_token="stale"))

        _, send = self._run([cost_page([{"Keys": ["AmazonS3", "1"], "Metrics": {}}])], manager)

        assert send.call_args_list[0][0][3]["TimePeriod"] == {"Start": "2024-03-01", "End": "2024-03-04"}
        assert "NextPageToken" not in send.call_args_list[0][0][3]

    def test_the_window_ends_tomorrow_so_todays_partial_costs_are_included(self) -> None:
        manager = FakeResumeManager()

        _, send = self._run([cost_page([])], manager)

        assert send.call_args_list[0][0][3]["TimePeriod"]["End"] == "2024-03-04"

    @pytest.mark.parametrize("endpoint", ["reservation_utilization_daily", "savings_plans_utilization_daily"])
    def test_utilization_endpoints_stop_at_today_because_aws_has_no_data_for_it_yet(self, endpoint: str) -> None:
        # Unlike cost-and-usage, AWS rejects a utilization request whose window reaches into
        # the current, still-in-progress day with DataUnavailableException.
        manager = FakeResumeManager()

        _, send = self._run([{}], manager, endpoint=endpoint)

        assert send.call_args_list[0][0][3]["TimePeriod"]["End"] == "2024-03-03"

    def test_wide_ranges_are_split_into_windows_walked_oldest_first(self) -> None:
        manager = FakeResumeManager()

        _, send = self._run([cost_page([]), cost_page([]), cost_page([])], manager, start_date="2023-09-01")

        boundaries = [
            (call[0][3]["TimePeriod"]["Start"], call[0][3]["TimePeriod"]["End"]) for call in send.call_args_list
        ]
        assert boundaries == [
            ("2023-09-01", "2023-12-02"),
            ("2023-12-02", "2024-03-03"),
            ("2024-03-03", "2024-03-04"),
        ]

    def test_an_incremental_run_asks_aws_only_for_the_restated_tail(self) -> None:
        manager = FakeResumeManager()

        _, send = self._run(
            [cost_page([])],
            manager,
            start_date="2023-01-01",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-03-01",
        )

        assert send.call_count == 1
        assert send.call_args_list[0][0][3]["TimePeriod"] == {"Start": "2024-02-23", "End": "2024-03-04"}

    def test_an_operation_without_pagination_issues_exactly_one_request_per_window(self) -> None:
        manager = FakeResumeManager()

        batches, send = self._run(
            [
                {
                    "SavingsPlansUtilizationsByTime": [
                        {
                            "TimePeriod": {"Start": "2024-03-01", "End": "2024-03-02"},
                            "Utilization": {"TotalCommitment": "10"},
                        }
                    ],
                    # A stray token must not restart the loop for an unpaginated operation.
                    "NextPageToken": "ignored",
                }
            ],
            manager,
            endpoint="savings_plans_utilization_daily",
        )

        assert send.call_count == 1
        assert batches[0][0]["total_commitment"] == 10.0

    def test_nothing_is_requested_when_the_watermark_is_already_current(self) -> None:
        manager = FakeResumeManager()

        batches, send = self._run([], manager, start_date="2024-03-04")

        assert batches == []
        assert send.call_count == 0
        assert manager.cleared is True
