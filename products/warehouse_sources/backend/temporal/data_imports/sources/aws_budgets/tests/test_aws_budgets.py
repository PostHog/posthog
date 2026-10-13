import json
import datetime as dt
from typing import Any, Optional, cast

import pytest
import time_machine
from unittest import mock

import requests
import structlog
from tenacity import wait_none

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_budgets import aws_budgets
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_budgets.aws_budgets import (
    AwsBudgetsError,
    AwsBudgetsResumeConfig,
    BudgetRef,
    error_for_response,
    fetch_account_id,
    get_rows,
    normalize_budget,
    probe_endpoint_permissions,
    resolve_history_window,
    resume_position,
    send_operation,
    validate_credentials,
)
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


class TestNormalizeBudget:
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


class TestErrorClassification:
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

    @pytest.mark.parametrize(
        "watermark",
        ["2024-05-20", "2024-05-20T00:00:00Z", dt.date(2024, 5, 20), dt.datetime(2024, 5, 20, tzinfo=dt.UTC)],
    )
    def test_incremental_rewinds_behind_the_watermark_to_re_read_restated_spend(self, watermark: Any) -> None:
        assert resolve_history_window(True, watermark, self.NOW).start == dt.datetime(2024, 5, 13, tzinfo=dt.UTC)


class TestResumePosition:
    BUDGETS = [
        BudgetRef(name="a", time_unit="MONTHLY"),
        BudgetRef(name="b", time_unit="MONTHLY"),
        BudgetRef(name="c", time_unit="DAILY"),
    ]

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


class TestGetFanoutRows:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel("2024-06-01T12:00:00Z", tick=False):
            yield

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

    def test_notifications_are_requested_for_every_budget_and_carry_no_time_period(self) -> None:
        _, send = self._run(
            [self.LISTED, {"Notifications": []}, {"Notifications": []}, {"Notifications": []}],
            FakeResumeManager(),
            endpoint="notifications",
        )

        requested = [call[0][3]["BudgetName"] for call in send.call_args_list[1:]]
        assert requested == ["monthly-cost", "yearly-cost", "daily-usage"]
        assert all("TimePeriod" not in call[0][3] for call in send.call_args_list[1:])

    def test_resuming_picks_up_at_the_saved_budget_and_page(self) -> None:
        manager = FakeResumeManager(AwsBudgetsResumeConfig(next_token="page-9", budget_name="daily-usage"))

        _, send = self._run([self.LISTED, history_page([], budget_name="daily-usage")], manager)

        assert [call[0][3]["BudgetName"] for call in send.call_args_list[1:]] == ["daily-usage"]
        assert send.call_args_list[1][0][3]["NextToken"] == "page-9"

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
