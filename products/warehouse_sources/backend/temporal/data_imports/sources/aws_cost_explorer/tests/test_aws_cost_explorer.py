import json
import datetime as dt
from typing import Any, Optional, cast

import pytest
import time_machine
from unittest import mock

import requests
import structlog
from tenacity import wait_none

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_explorer import aws_cost_explorer
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_explorer.aws_cost_explorer import (
    GENERIC_VALIDATION_ERROR,
    TRANSIENT_VALIDATION_ERROR,
    VALIDATION_ERROR_MESSAGES,
    AwsCostExplorerError,
    AwsCostExplorerResumeConfig,
    AwsCostExplorerThrottledError,
    build_payload,
    error_for_response,
    get_rows,
    resolve_start_date,
    send_operation,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_explorer.settings import (
    AWS_COST_EXPLORER_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

LOGGER = structlog.get_logger()

COST_DAILY = AWS_COST_EXPLORER_ENDPOINTS["cost_and_usage_daily"]
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


class TestResolveStartDate:
    END = dt.date(2024, 6, 1)

    def test_defaults_to_a_year_back_when_no_start_date_is_configured(self) -> None:
        assert resolve_start_date(None, COST_DAILY, False, None, self.END) == dt.date(2023, 6, 2)

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

    def test_ignores_an_unparseable_watermark(self) -> None:
        assert resolve_start_date("2024-01-01", COST_DAILY, True, "not-a-date", self.END) == dt.date(2024, 1, 1)


class TestBuildPayload:
    WINDOW = aws_cost_explorer.TimeWindow(start=dt.date(2024, 3, 1), end=dt.date(2024, 4, 1))

    def test_a_token_is_never_sent_to_an_operation_that_cannot_paginate(self) -> None:
        # GetSavingsPlansUtilization has no pagination; sending a token would be rejected.
        assert build_payload(SAVINGS_PLANS, self.WINDOW, "tok") == {
            "TimePeriod": {"Start": "2024-03-01", "End": "2024-04-01"},
            "Granularity": "DAILY",
        }


class TestErrorClassification:
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

    @pytest.mark.parametrize(
        "code,expected",
        [
            ("AccessDeniedException", VALIDATION_ERROR_MESSAGES["AccessDeniedException"]),
            ("ExpiredTokenException", VALIDATION_ERROR_MESSAGES["ExpiredTokenException"]),
            ("ThrottlingException", TRANSIENT_VALIDATION_ERROR),
            ("HTTP 503", TRANSIENT_VALIDATION_ERROR),
            ("SomeUnmappedException", GENERIC_VALIDATION_ERROR),
        ],
    )
    def test_an_api_error_is_translated_instead_of_echoing_the_aws_text(self, code: str, expected: str) -> None:
        # A denial names the calling identity, so the AWS text can never reach the wizard.
        raw = (
            f"AWS Cost Explorer request failed: {code} - User: arn:aws:iam::000000000000:user/example is not authorized"
        )

        with mock.patch.object(aws_cost_explorer, "send_operation", side_effect=AwsCostExplorerError(raw, code)):
            assert validate_credentials("key", "secret", None) == (False, expected)

    def test_a_transport_failure_does_not_leak_internals(self) -> None:
        with mock.patch.object(aws_cost_explorer, "send_operation", side_effect=requests.ConnectionError("boom")):
            assert validate_credentials("key", "secret", None) == (
                False,
                "Could not reach the AWS Cost Explorer API",
            )


class TestGetRows:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel("2024-03-03T12:00:00Z", tick=False):
            yield

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
