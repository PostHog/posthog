import json
import datetime as dt
from typing import Any, Optional, cast

import pytest
from freezegun import freeze_time
from unittest import mock

import requests
import structlog
from tenacity import wait_none

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_budgets import aws_budgets
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_budgets.aws_budgets import (
    AwsBudgetsError,
    AwsBudgetsResumeConfig,
    AwsBudgetsThrottledError,
    BudgetRef,
    error_for_response,
    fetch_account_id,
    get_rows,
    normalize_budget,
    normalize_history_rows,
    normalize_notification_rows,
    probe_endpoint_permissions,
    resolve_history_window,
    resume_position,
    send_operation,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_budgets.settings import BUDGETS_ENDPOINT_URL
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

LOGGER = structlog.get_logger()

ACCOUNT_ID = "123456789012"

MARCH_1 = 1709251200  # 2024-03-01T00:00:00Z
APRIL_1 = 1711929600  # 2024-04-01T00:00:00Z


class FakeResumeManager(ResumableSourceManager[AwsBudgetsResumeConfig]):
    def __init__(self, state: Optional[AwsBudgetsResumeConfig] = None) -> None:
        self.state = state
        self.saved: list[AwsBudgetsResumeConfig] = []
        self.cleared = False

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[AwsBudgetsResumeConfig]:
        return self.state

    def save_state(self, data: AwsBudgetsResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared = True


def without_retry_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cast(Any, send_operation).retry, "wait", wait_none())


def make_response(
    status_code: int, payload: Optional[dict[str, Any]] = None, headers: Optional[dict[str, str]] = None
) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.headers.update(headers or {})
    response._content = json.dumps(payload if payload is not None else {}).encode()
    return response


def make_xml_response(status_code: int, body: str) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = body.encode()
    return response


def budgets_page(budgets: list[dict[str, Any]], next_token: Optional[str] = None) -> dict[str, Any]:
    body: dict[str, Any] = {"Budgets": budgets}
    if next_token is not None:
        body["NextToken"] = next_token
    return body


def history_page(
    amounts: list[dict[str, Any]],
    next_token: Optional[str] = None,
    budget_name: str = "monthly-cost",
    time_unit: str = "MONTHLY",
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "BudgetPerformanceHistory": {
            "BudgetName": budget_name,
            "BudgetType": "COST",
            "TimeUnit": time_unit,
            "BudgetedAndActualAmountsList": amounts,
        }
    }
    if next_token is not None:
        body["NextToken"] = next_token
    return body


FULL_BUDGET: dict[str, Any] = {
    "BudgetName": "monthly-cost",
    "BudgetType": "COST",
    "TimeUnit": "MONTHLY",
    "BudgetLimit": {"Amount": "1000.0", "Unit": "USD"},
    "PlannedBudgetLimits": {"1709251200": {"Amount": "900.0", "Unit": "USD"}},
    "CostFilters": {"Service": ["AmazonS3"]},
    "FilterExpression": {"Dimensions": {"Key": "SERVICE", "Values": ["AmazonS3"]}},
    "Metrics": ["UnblendedCost"],
    "CostTypes": {"IncludeTax": True, "UseAmortized": False},
    "TimePeriod": {"Start": MARCH_1, "End": APRIL_1},
    "CalculatedSpend": {
        "ActualSpend": {"Amount": "412.75", "Unit": "USD"},
        "ForecastedSpend": {"Amount": "980.10", "Unit": "USD"},
    },
    "LastUpdatedTime": MARCH_1,
    "AutoAdjustData": {
        "AutoAdjustType": "HISTORICAL",
        "HistoricalOptions": {"BudgetAdjustmentPeriod": 6, "LookBackAvailablePeriods": 3},
        "LastAutoAdjustTime": MARCH_1,
    },
    "BillingViewArn": "arn:aws:billing::123456789012:billingview/primary",
    "HealthStatus": {"Status": "UNHEALTHY", "StatusReason": "FILTER_INVALID", "LastUpdatedTime": MARCH_1},
}


class TestNormalizeBudget:
    def test_a_full_budget_flattens_into_stable_columns(self) -> None:
        row = normalize_budget(FULL_BUDGET)

        assert row["budget_name"] == "monthly-cost"
        assert row["budget_type"] == "COST"
        assert row["time_unit"] == "MONTHLY"
        # AWS reports every monetary amount as a string; converting would lose precision the
        # customer's own bill is stated in.
        assert row["budget_limit_amount"] == "1000.0"
        assert row["budget_limit_unit"] == "USD"
        assert row["actual_spend_amount"] == "412.75"
        assert row["forecasted_spend_amount"] == "980.10"
        assert row["time_period_start"] == dt.datetime(2024, 3, 1, tzinfo=dt.UTC)
        assert row["time_period_end"] == dt.datetime(2024, 4, 1, tzinfo=dt.UTC)
        assert row["last_updated_time"] == dt.datetime(2024, 3, 1, tzinfo=dt.UTC)
        assert row["auto_adjust_type"] == "HISTORICAL"
        assert row["auto_adjust_budget_adjustment_period"] == 6
        assert row["auto_adjust_look_back_available_periods"] == 3
        assert row["auto_adjust_last_time"] == dt.datetime(2024, 3, 1, tzinfo=dt.UTC)
        assert row["health_status"] == "UNHEALTHY"
        assert row["health_status_reason"] == "FILTER_INVALID"
        assert row["health_status_last_updated_time"] == dt.datetime(2024, 3, 1, tzinfo=dt.UTC)
        assert row["cost_types_include_tax"] is True
        assert row["cost_types_use_amortized"] is False

    def test_customer_defined_maps_are_kept_whole_instead_of_becoming_columns(self) -> None:
        row = normalize_budget(FULL_BUDGET)

        assert row["planned_budget_limits"] == {"1709251200": {"Amount": "900.0", "Unit": "USD"}}
        assert row["cost_filters"] == {"Service": ["AmazonS3"]}
        assert row["filter_expression"] == {"Dimensions": {"Key": "SERVICE", "Values": ["AmazonS3"]}}
        assert row["metrics"] == ["UnblendedCost"]

    def test_a_sparse_budget_keeps_the_same_columns(self) -> None:
        # Budget types other than COST carry no cost types, and RI budgets carry no limit; the
        # Arrow schema must not shift between pages depending on which budgets landed in them.
        sparse = normalize_budget({"BudgetName": "ri-coverage", "BudgetType": "RI_COVERAGE", "TimeUnit": "DAILY"})

        assert set(sparse.keys()) == set(normalize_budget(FULL_BUDGET).keys())
        assert sparse["budget_limit_amount"] is None
        assert sparse["cost_types_include_tax"] is None
        assert sparse["health_status"] is None

    @pytest.mark.parametrize(
        "value,expected",
        [
            (MARCH_1, dt.datetime(2024, 3, 1, tzinfo=dt.UTC)),
            (1709251200.5, dt.datetime(2024, 3, 1, 0, 0, 0, 500000, tzinfo=dt.UTC)),
            ("2024-03-01T00:00:00Z", dt.datetime(2024, 3, 1, tzinfo=dt.UTC)),
            (None, None),
            ("not-a-date", None),
        ],
    )
    def test_timestamps_are_parsed_from_the_json_protocols_epoch_seconds(self, value: Any, expected: Any) -> None:
        assert normalize_budget({"LastUpdatedTime": value})["last_updated_time"] == expected


class TestNormalizeHistoryRows:
    AMOUNTS = [
        {
            "BudgetedAmount": {"Amount": "1000.0", "Unit": "USD"},
            "ActualAmount": {"Amount": "812.5", "Unit": "USD"},
            "TimePeriod": {"Start": MARCH_1, "End": APRIL_1},
        },
        {
            "BudgetedAmount": {"Amount": "1000.0", "Unit": "USD"},
            "ActualAmount": {"Amount": "97.25", "Unit": "USD"},
            "TimePeriod": {"Start": APRIL_1, "End": APRIL_1 + 86400},
        },
    ]

    def test_one_row_per_period_carries_the_budgets_identity(self) -> None:
        rows = normalize_history_rows(BudgetRef(name="monthly-cost", time_unit="MONTHLY"), history_page(self.AMOUNTS))

        assert [row["period_start"] for row in rows] == [
            dt.datetime(2024, 3, 1, tzinfo=dt.UTC),
            dt.datetime(2024, 4, 1, tzinfo=dt.UTC),
        ]
        assert [row["actual_amount"] for row in rows] == ["812.5", "97.25"]
        assert {row["budget_name"] for row in rows} == {"monthly-cost"}
        assert rows[0]["budgeted_amount"] == "1000.0"
        assert rows[0]["period_end"] == dt.datetime(2024, 4, 1, tzinfo=dt.UTC)
        assert rows[0]["time_unit"] == "MONTHLY"

    def test_the_budget_name_falls_back_to_the_parent_when_aws_omits_it(self) -> None:
        # The primary key is (budget_name, period_start), so a missing name would collapse every
        # budget's history onto one set of keys.
        body = {"BudgetPerformanceHistory": {"BudgetedAndActualAmountsList": self.AMOUNTS}}

        rows = normalize_history_rows(BudgetRef(name="quarterly-usage", time_unit="QUARTERLY"), body)

        assert {row["budget_name"] for row in rows} == {"quarterly-usage"}

    @pytest.mark.parametrize("body", [{}, {"BudgetPerformanceHistory": {}}, {"BudgetPerformanceHistory": None}])
    def test_a_budget_with_no_recorded_history_yields_no_rows(self, body: dict[str, Any]) -> None:
        assert normalize_history_rows(BudgetRef(name="monthly-cost", time_unit="MONTHLY"), body) == []


class TestNormalizeNotificationRows:
    def test_rows_carry_the_budget_name_that_makes_the_primary_key_unique(self) -> None:
        body = {
            "Notifications": [
                {
                    "NotificationType": "ACTUAL",
                    "ComparisonOperator": "GREATER_THAN",
                    "Threshold": 80.0,
                    "ThresholdType": "PERCENTAGE",
                    "NotificationState": "ALARM",
                },
                {
                    "NotificationType": "FORECASTED",
                    "ComparisonOperator": "GREATER_THAN",
                    "Threshold": 100.0,
                    "ThresholdType": "PERCENTAGE",
                    "NotificationState": "OK",
                },
            ]
        }

        rows = normalize_notification_rows(BudgetRef(name="monthly-cost", time_unit="MONTHLY"), body)

        assert [row["notification_type"] for row in rows] == ["ACTUAL", "FORECASTED"]
        assert [row["threshold"] for row in rows] == [80.0, 100.0]
        assert {row["budget_name"] for row in rows} == {"monthly-cost"}
        assert rows[0]["notification_state"] == "ALARM"

    def test_a_budget_with_no_notifications_yields_no_rows(self) -> None:
        assert normalize_notification_rows(BudgetRef(name="monthly-cost", time_unit="MONTHLY"), {}) == []


class TestErrorClassification:
    @pytest.mark.parametrize("code", ["ThrottlingException", "TooManyRequestsException", "RequestLimitExceeded"])
    def test_throttling_codes_are_retryable(self, code: str) -> None:
        response = make_response(400, {"__type": f"com.amazon.coral.availability#{code}", "message": "slow down"})

        error = error_for_response(response)

        assert isinstance(error, AwsBudgetsThrottledError)
        assert f"AWS Budgets request failed: {code}" in str(error)

    @pytest.mark.parametrize(
        "code", ["AccessDeniedException", "UnrecognizedClientException", "ExpiredTokenException", "NotFoundException"]
    )
    def test_permanent_codes_are_not_retryable_and_stringify_for_the_source_mapping(self, code: str) -> None:
        response = make_response(400, {"__type": code, "message": "nope"})

        error = error_for_response(response)

        assert not isinstance(error, AwsBudgetsThrottledError)
        assert str(error) == f"AWS Budgets request failed: {code} - nope"

    def test_the_error_type_header_wins_over_the_body(self) -> None:
        response = make_response(
            400,
            {"message": "nope"},
            headers={"x-amzn-ErrorType": "AccessDeniedException:http://internal.amazon.com/coral/"},
        )

        assert str(error_for_response(response)) == "AWS Budgets request failed: AccessDeniedException - nope"

    def test_a_non_json_error_body_still_produces_a_usable_message(self) -> None:
        response = requests.Response()
        response.status_code = 503
        response._content = b"<html>gateway</html>"

        assert "HTTP 503" in str(error_for_response(response))


class TestSendOperation:
    def test_requests_are_sigv4_signed_for_the_global_endpoint_and_dispatched_via_x_amz_target(self) -> None:
        session = mock.MagicMock(spec=requests.Session)
        session.post.return_value = make_response(200, {"Budgets": []})

        with freeze_time("2024-03-05T10:00:00Z"):
            send_operation(
                session, aws_budgets.Credentials("AKIAEXAMPLE", "secret"), "DescribeBudgets", {"AccountId": ACCOUNT_ID}
            )

        _, kwargs = session.post.call_args
        assert session.post.call_args[0][0] == BUDGETS_ENDPOINT_URL
        assert kwargs["headers"]["X-Amz-Target"] == "AWSBudgetServiceGateway.DescribeBudgets"
        assert kwargs["headers"]["Content-Type"] == "application/x-amz-json-1.1"
        # Budgets is global: signing anywhere but us-east-1 returns SignatureDoesNotMatch.
        assert kwargs["headers"]["Authorization"].startswith(
            "AWS4-HMAC-SHA256 Credential=AKIAEXAMPLE/20240305/us-east-1/budgets/aws4_request"
        )
        assert json.loads(kwargs["data"]) == {"AccountId": ACCOUNT_ID}

    def test_temporary_credentials_carry_the_session_token(self) -> None:
        session = mock.MagicMock(spec=requests.Session)
        session.post.return_value = make_response(200, {})

        send_operation(
            session, aws_budgets.Credentials("AKIAEXAMPLE", "secret", "session-token"), "DescribeBudgets", {}
        )

        assert session.post.call_args[1]["headers"]["X-Amz-Security-Token"] == "session-token"

    def test_throttled_calls_are_retried_until_they_succeed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        without_retry_backoff(monkeypatch)
        session = mock.MagicMock(spec=requests.Session)
        session.post.side_effect = [
            make_response(400, {"__type": "ThrottlingException", "message": "slow down"}),
            make_response(200, {"Budgets": []}),
        ]

        body = send_operation(session, aws_budgets.Credentials("k", "s"), "DescribeBudgets", {})

        assert body == {"Budgets": []}
        assert session.post.call_count == 2

    def test_permanent_errors_are_raised_without_retrying(self, monkeypatch: pytest.MonkeyPatch) -> None:
        without_retry_backoff(monkeypatch)
        session = mock.MagicMock(spec=requests.Session)
        session.post.return_value = make_response(400, {"__type": "AccessDeniedException", "message": "denied"})

        with pytest.raises(AwsBudgetsError):
            send_operation(session, aws_budgets.Credentials("k", "s"), "DescribeBudgets", {})

        assert session.post.call_count == 1


IDENTITY_XML = """<GetCallerIdentityResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/">
  <GetCallerIdentityResult>
    <Arn>arn:aws:iam::123456789012:user/finops</Arn>
    <UserId>AIDAEXAMPLE</UserId>
    <Account>123456789012</Account>
  </GetCallerIdentityResult>
</GetCallerIdentityResponse>"""

STS_ERROR_XML = """<ErrorResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/">
  <Error>
    <Type>Sender</Type>
    <Code>InvalidClientTokenId</Code>
    <Message>The security token included in the request is invalid.</Message>
  </Error>
</ErrorResponse>"""


class TestFetchAccountId:
    def test_the_account_id_is_read_from_the_signed_sts_call(self) -> None:
        session = mock.MagicMock(spec=requests.Session)
        session.post.return_value = make_xml_response(200, IDENTITY_XML)

        assert fetch_account_id(session, aws_budgets.Credentials("AKIAEXAMPLE", "secret")) == ACCOUNT_ID
        assert session.post.call_args[0][0] == "https://sts.amazonaws.com/"
        assert session.post.call_args[1]["data"] == b"Action=GetCallerIdentity&Version=2011-06-15"
        assert session.post.call_args[1]["headers"]["Authorization"].startswith(
            "AWS4-HMAC-SHA256 Credential=AKIAEXAMPLE/"
        )

    def test_an_sts_error_surfaces_the_aws_code_so_the_source_can_map_it(self) -> None:
        session = mock.MagicMock(spec=requests.Session)
        session.post.return_value = make_xml_response(403, STS_ERROR_XML)

        with pytest.raises(AwsBudgetsError) as error:
            fetch_account_id(session, aws_budgets.Credentials("k", "s"))

        assert str(error.value).startswith("AWS STS request failed: InvalidClientTokenId - ")

    @pytest.mark.parametrize(
        "body",
        [
            "<GetCallerIdentityResponse><GetCallerIdentityResult><Arn>arn</Arn></GetCallerIdentityResult></GetCallerIdentityResponse>",
            "<GetCallerIdentityResponse><GetCallerIdentityResult><Account>12345</Account></GetCallerIdentityResult></GetCallerIdentityResponse>",
            "not xml at all",
        ],
    )
    def test_a_response_without_a_usable_account_id_fails_loudly(self, body: str) -> None:
        # Every Budgets operation requires the account id, so guessing one would produce a
        # confusing NotFoundException much later in the sync.
        session = mock.MagicMock(spec=requests.Session)
        session.post.return_value = make_xml_response(200, body)

        with pytest.raises(AwsBudgetsError):
            fetch_account_id(session, aws_budgets.Credentials("k", "s"))


class TestResolveHistoryWindow:
    NOW = dt.datetime(2024, 6, 1, 12, 0, tzinfo=dt.UTC)

    def test_a_full_refresh_reaches_back_a_year_to_cover_every_grain(self) -> None:
        window = resolve_history_window(False, None, self.NOW)

        assert window.start == dt.datetime(2023, 6, 2, 12, 0, tzinfo=dt.UTC)
        # The period in progress is included so its actual spend keeps merging.
        assert window.end == dt.datetime(2024, 6, 2, 12, 0, tzinfo=dt.UTC)

    @pytest.mark.parametrize(
        "watermark",
        ["2024-05-20", "2024-05-20T00:00:00Z", dt.date(2024, 5, 20), dt.datetime(2024, 5, 20, tzinfo=dt.UTC)],
    )
    def test_incremental_rewinds_behind_the_watermark_to_re_read_restated_spend(self, watermark: Any) -> None:
        assert resolve_history_window(True, watermark, self.NOW).start == dt.datetime(2024, 5, 13, tzinfo=dt.UTC)

    def test_a_watermark_older_than_the_lookback_floor_does_not_widen_the_window(self) -> None:
        assert resolve_history_window(True, "2019-01-01", self.NOW).start == dt.datetime(
            2023, 6, 2, 12, 0, tzinfo=dt.UTC
        )

    @pytest.mark.parametrize("watermark", [None, "not-a-date"])
    def test_an_unusable_watermark_falls_back_to_the_full_window(self, watermark: Any) -> None:
        assert resolve_history_window(True, watermark, self.NOW).start == dt.datetime(2023, 6, 2, 12, 0, tzinfo=dt.UTC)


class TestResumePosition:
    BUDGETS = [
        BudgetRef(name="a", time_unit="MONTHLY"),
        BudgetRef(name="b", time_unit="MONTHLY"),
        BudgetRef(name="c", time_unit="DAILY"),
    ]

    def test_a_saved_budget_resumes_at_that_budget_and_page(self) -> None:
        assert resume_position(self.BUDGETS, AwsBudgetsResumeConfig(next_token="tok", budget_name="b")) == (1, "tok")

    @pytest.mark.parametrize(
        "resume",
        [None, AwsBudgetsResumeConfig(), AwsBudgetsResumeConfig(next_token="tok", budget_name="deleted")],
    )
    def test_anything_we_cannot_place_restarts_the_fan_out(self, resume: Optional[AwsBudgetsResumeConfig]) -> None:
        # A budget deleted since the last attempt must not silently skip the budgets before it.
        assert resume_position(self.BUDGETS, resume) == (0, None)


class TestGetBudgetRows:
    def _run(
        self, responses: list[Any], manager: FakeResumeManager
    ) -> tuple[list[list[dict[str, Any]]], mock.MagicMock]:
        with (
            mock.patch.object(aws_budgets, "fetch_account_id", return_value=ACCOUNT_ID),
            mock.patch.object(aws_budgets, "send_operation", side_effect=responses) as send,
        ):
            batches = list(
                get_rows(
                    aws_access_key_id="key",
                    aws_secret_access_key="secret",
                    aws_session_token=None,
                    endpoint="budgets",
                    resumable_source_manager=manager,
                    should_use_incremental_field=False,
                    db_incremental_field_last_value=None,
                    logger=LOGGER,
                )
            )
        return batches, send

    def test_pagination_stops_when_aws_stops_returning_a_token(self) -> None:
        manager = FakeResumeManager()

        batches, send = self._run(
            [
                budgets_page([{"BudgetName": "a"}], next_token="page-2"),
                budgets_page([{"BudgetName": "b"}]),
            ],
            manager,
        )

        assert [row["budget_name"] for batch in batches for row in batch] == ["a", "b"]
        assert send.call_args_list[0][0][3].get("NextToken") is None
        assert send.call_args_list[1][0][3]["NextToken"] == "page-2"

    def test_the_filter_expression_is_requested_because_aws_hides_it_by_default(self) -> None:
        _, send = self._run([budgets_page([])], FakeResumeManager())

        assert send.call_args_list[0][0][3]["ShowFilterExpression"] is True
        assert send.call_args_list[0][0][3]["AccountId"] == ACCOUNT_ID

    def test_state_is_saved_after_each_page_and_cleared_once_the_walk_completes(self) -> None:
        manager = FakeResumeManager()

        self._run(
            [budgets_page([{"BudgetName": "a"}], next_token="page-2"), budgets_page([{"BudgetName": "b"}])], manager
        )

        assert manager.saved == [
            AwsBudgetsResumeConfig(next_token="page-2"),
            AwsBudgetsResumeConfig(next_token=None),
        ]
        assert manager.cleared is True

    def test_a_saved_token_resumes_the_walk_where_it_stopped(self) -> None:
        manager = FakeResumeManager(AwsBudgetsResumeConfig(next_token="page-7"))

        _, send = self._run([budgets_page([{"BudgetName": "a"}])], manager)

        assert send.call_count == 1
        assert send.call_args_list[0][0][3]["NextToken"] == "page-7"

    @pytest.mark.parametrize("code", ["ExpiredNextTokenException", "InvalidNextTokenException"])
    def test_a_stale_saved_token_restarts_the_walk_rather_than_failing_the_job(self, code: str) -> None:
        manager = FakeResumeManager(AwsBudgetsResumeConfig(next_token="stale"))

        batches, send = self._run(
            [
                AwsBudgetsError(f"AWS Budgets request failed: {code} - gone"),
                budgets_page([{"BudgetName": "a"}]),
            ],
            manager,
        )

        assert [row["budget_name"] for batch in batches for row in batch] == ["a"]
        assert "NextToken" not in send.call_args_list[1][0][3]

    def test_a_stale_token_error_on_a_fresh_walk_is_not_swallowed(self) -> None:
        # Without a saved token the error means something else is wrong; retrying from scratch
        # would loop forever.
        with pytest.raises(AwsBudgetsError):
            self._run(
                [AwsBudgetsError("AWS Budgets request failed: InvalidNextTokenException - gone")], FakeResumeManager()
            )


@freeze_time("2024-06-01T12:00:00Z")
class TestGetFanoutRows:
    LISTED = budgets_page(
        [
            {"BudgetName": "monthly-cost", "TimeUnit": "MONTHLY"},
            {"BudgetName": "yearly-cost", "TimeUnit": "ANNUALLY"},
            {"BudgetName": "daily-usage", "TimeUnit": "DAILY"},
        ]
    )

    def _run(
        self,
        responses: list[Any],
        manager: FakeResumeManager,
        endpoint: str = "budget_performance_history",
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[list[dict[str, Any]]], mock.MagicMock]:
        with (
            mock.patch.object(aws_budgets, "fetch_account_id", return_value=ACCOUNT_ID),
            mock.patch.object(aws_budgets, "send_operation", side_effect=responses) as send,
        ):
            batches = list(
                get_rows(
                    aws_access_key_id="key",
                    aws_secret_access_key="secret",
                    aws_session_token=None,
                    endpoint=endpoint,
                    resumable_source_manager=manager,
                    should_use_incremental_field=should_use_incremental_field,
                    db_incremental_field_last_value=db_incremental_field_last_value,
                    logger=LOGGER,
                )
            )
        return batches, send

    def test_history_skips_budgets_aws_keeps_no_history_for(self) -> None:
        # DescribeBudgetPerformanceHistory covers DAILY, MONTHLY and QUARTERLY budgets only.
        _, send = self._run(
            [self.LISTED, history_page([], budget_name="monthly-cost"), history_page([], budget_name="daily-usage")],
            FakeResumeManager(),
        )

        requested = [call[0][3]["BudgetName"] for call in send.call_args_list[1:]]
        assert requested == ["monthly-cost", "daily-usage"]

    def test_notifications_are_requested_for_every_budget_and_carry_no_time_period(self) -> None:
        _, send = self._run(
            [self.LISTED, {"Notifications": []}, {"Notifications": []}, {"Notifications": []}],
            FakeResumeManager(),
            endpoint="notifications",
        )

        requested = [call[0][3]["BudgetName"] for call in send.call_args_list[1:]]
        assert requested == ["monthly-cost", "yearly-cost", "daily-usage"]
        assert all("TimePeriod" not in call[0][3] for call in send.call_args_list[1:])

    def test_the_history_window_is_sent_as_epoch_seconds(self) -> None:
        _, send = self._run(
            [self.LISTED, history_page([]), history_page([])],
            FakeResumeManager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-05-20",
        )

        assert send.call_args_list[1][0][3]["TimePeriod"] == {
            "Start": int(dt.datetime(2024, 5, 13, tzinfo=dt.UTC).timestamp()),
            "End": int(dt.datetime(2024, 6, 2, 12, 0, tzinfo=dt.UTC).timestamp()),
        }

    def test_state_records_the_budget_being_walked_so_a_retry_does_not_restart_the_fan_out(self) -> None:
        manager = FakeResumeManager()

        self._run(
            [
                self.LISTED,
                history_page([], next_token="page-2", budget_name="monthly-cost"),
                history_page([], budget_name="monthly-cost"),
                history_page([], budget_name="daily-usage"),
            ],
            manager,
        )

        assert manager.saved == [
            AwsBudgetsResumeConfig(next_token="page-2", budget_name="monthly-cost"),
            AwsBudgetsResumeConfig(next_token=None, budget_name="monthly-cost"),
            AwsBudgetsResumeConfig(next_token=None, budget_name="daily-usage"),
        ]
        assert manager.cleared is True

    def test_resuming_picks_up_at_the_saved_budget_and_page(self) -> None:
        manager = FakeResumeManager(AwsBudgetsResumeConfig(next_token="page-9", budget_name="daily-usage"))

        _, send = self._run([self.LISTED, history_page([], budget_name="daily-usage")], manager)

        assert [call[0][3]["BudgetName"] for call in send.call_args_list[1:]] == ["daily-usage"]
        assert send.call_args_list[1][0][3]["NextToken"] == "page-9"

    def test_the_saved_page_token_is_not_reused_on_the_next_budget(self) -> None:
        # A token belongs to one budget's walk; sending it to the next budget would be rejected.
        manager = FakeResumeManager(AwsBudgetsResumeConfig(next_token="page-9", budget_name="monthly-cost"))

        _, send = self._run(
            [self.LISTED, history_page([], budget_name="monthly-cost"), history_page([], budget_name="daily-usage")],
            manager,
        )

        assert send.call_args_list[1][0][3]["NextToken"] == "page-9"
        assert "NextToken" not in send.call_args_list[2][0][3]

    @pytest.mark.parametrize("code", ["NotFoundException", "BillingViewHealthStatusException"])
    def test_a_budget_aws_cannot_report_on_is_skipped_without_failing_the_sync(self, code: str) -> None:
        batches, send = self._run(
            [
                self.LISTED,
                AwsBudgetsError(f"AWS Budgets request failed: {code} - nope"),
                history_page(
                    [
                        {
                            "BudgetedAmount": {"Amount": "5", "Unit": "USD"},
                            "ActualAmount": {"Amount": "1", "Unit": "USD"},
                            "TimePeriod": {"Start": MARCH_1, "End": APRIL_1},
                        }
                    ],
                    budget_name="daily-usage",
                ),
            ],
            FakeResumeManager(),
        )

        assert [row["budget_name"] for batch in batches for row in batch] == ["daily-usage"]
        assert send.call_count == 3

    def test_a_denial_mid_fan_out_still_fails_the_sync(self) -> None:
        # Skipping it would silently produce a table missing most of its rows.
        with pytest.raises(AwsBudgetsError):
            self._run(
                [self.LISTED, AwsBudgetsError("AWS Budgets request failed: AccessDeniedException - denied")],
                FakeResumeManager(),
            )

    def test_an_account_with_no_eligible_budgets_makes_no_further_requests(self) -> None:
        manager = FakeResumeManager()

        batches, send = self._run([budgets_page([{"BudgetName": "yearly", "TimeUnit": "ANNUALLY"}])], manager)

        assert batches == []
        assert send.call_count == 1
        assert manager.cleared is True


class TestValidateCredentials:
    def test_missing_credentials_short_circuit_without_a_request(self) -> None:
        with mock.patch.object(aws_budgets, "fetch_account_id") as fetch:
            assert validate_credentials("", "secret", None) == (
                False,
                "AWS access key ID and secret access key are required",
            )

        fetch.assert_not_called()

    def test_a_successful_probe_validates(self) -> None:
        with (
            mock.patch.object(aws_budgets, "fetch_account_id", return_value=ACCOUNT_ID),
            mock.patch.object(aws_budgets, "send_operation", return_value=budgets_page([])) as send,
        ):
            assert validate_credentials("key", "secret", None) == (True, None)

        assert send.call_args[0][2] == "DescribeBudgets"

    def test_a_rejected_key_is_reported_with_the_aws_code(self) -> None:
        error = AwsBudgetsError("AWS STS request failed: InvalidClientTokenId - bad key")

        with mock.patch.object(aws_budgets, "fetch_account_id", side_effect=error):
            assert validate_credentials("key", "secret", None) == (False, str(error))

    def test_a_genuine_key_without_budgets_permissions_can_still_connect(self) -> None:
        # Per-table access is reported in the schema picker; blocking source creation would stop a
        # user who only wants the tables their key can read.
        with (
            mock.patch.object(aws_budgets, "fetch_account_id", return_value=ACCOUNT_ID),
            mock.patch.object(
                aws_budgets,
                "send_operation",
                side_effect=AwsBudgetsError("AWS Budgets request failed: AccessDeniedException - denied"),
            ),
        ):
            assert validate_credentials("key", "secret", None) == (True, None)

    def test_a_denial_for_a_named_schema_is_reported(self) -> None:
        with (
            mock.patch.object(aws_budgets, "fetch_account_id", return_value=ACCOUNT_ID),
            mock.patch.object(
                aws_budgets,
                "send_operation",
                side_effect=AwsBudgetsError("AWS Budgets request failed: AccessDeniedException - denied"),
            ),
        ):
            valid, reason = validate_credentials("key", "secret", None, schema_name="budgets")

        assert valid is False
        assert reason == "The connected IAM user or role is not allowed to read this table"

    def test_a_transport_failure_does_not_leak_internals(self) -> None:
        with mock.patch.object(aws_budgets, "fetch_account_id", side_effect=requests.ConnectionError("boom")):
            assert validate_credentials("key", "secret", None) == (
                False,
                "Could not reach AWS to check these credentials. Please try again.",
            )


class TestProbeEndpointPermissions:
    def test_reachable_endpoints_report_no_reason(self) -> None:
        with (
            mock.patch.object(aws_budgets, "fetch_account_id", return_value=ACCOUNT_ID),
            mock.patch.object(
                aws_budgets,
                "send_operation",
                side_effect=lambda *args, **kwargs: budgets_page([{"BudgetName": "a", "TimeUnit": "MONTHLY"}]),
            ),
        ):
            reasons = probe_endpoint_permissions("key", "secret", None, ["budgets", "notifications"])

        assert reasons == {"budgets": None, "notifications": None}

    def test_a_denied_endpoint_names_the_problem(self) -> None:
        with (
            mock.patch.object(aws_budgets, "fetch_account_id", return_value=ACCOUNT_ID),
            mock.patch.object(
                aws_budgets,
                "send_operation",
                side_effect=AwsBudgetsError("AWS Budgets request failed: AccessDeniedException - denied"),
            ),
        ):
            reasons = probe_endpoint_permissions("key", "secret", None, ["budgets"])

        assert reasons == {"budgets": "The connected IAM user or role is not allowed to read this table"}

    @pytest.mark.parametrize(
        "failure",
        [
            AwsBudgetsError("AWS Budgets request failed: ThrottlingException - slow down"),
            requests.ConnectionError("boom"),
        ],
    )
    def test_a_blip_leaves_the_endpoint_reported_as_reachable(self, failure: Exception) -> None:
        # Otherwise a throttle would hide tables from the schema picker.
        with (
            mock.patch.object(aws_budgets, "fetch_account_id", return_value=ACCOUNT_ID),
            mock.patch.object(aws_budgets, "send_operation", side_effect=failure),
        ):
            assert probe_endpoint_permissions("key", "secret", None, ["budgets"]) == {"budgets": None}

    def test_credentials_aws_will_not_identify_leave_every_endpoint_unjudged(self) -> None:
        with mock.patch.object(aws_budgets, "fetch_account_id", side_effect=requests.ConnectionError("boom")):
            assert probe_endpoint_permissions("key", "secret", None, ["budgets", "notifications"]) == {
                "budgets": None,
                "notifications": None,
            }
