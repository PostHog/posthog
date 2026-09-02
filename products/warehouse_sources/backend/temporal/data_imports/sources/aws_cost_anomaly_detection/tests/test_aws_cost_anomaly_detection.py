import json
import datetime as dt
from typing import Any, Optional, cast

import pytest
from freezegun import freeze_time
from unittest import mock

import requests
import structlog
from tenacity import wait_none

from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_anomaly_detection import (
    aws_cost_anomaly_detection,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_anomaly_detection.aws_cost_anomaly_detection import (
    ENABLEMENT_MESSAGE,
    AwsCostAnomalyDetectionError,
    AwsCostAnomalyDetectionResumeConfig,
    AwsCostAnomalyDetectionThrottledError,
    build_payload,
    error_for_response,
    get_rows,
    normalize_row,
    probe_endpoint_permissions,
    resolve_date_interval_start,
    send_operation,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_cost_anomaly_detection.settings import (
    AWS_COST_ANOMALY_DETECTION_ENDPOINTS,
    CE_ENDPOINT_URL,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

LOGGER = structlog.get_logger()

ANOMALIES = AWS_COST_ANOMALY_DETECTION_ENDPOINTS["anomalies"]
MONITORS = AWS_COST_ANOMALY_DETECTION_ENDPOINTS["anomaly_monitors"]
SUBSCRIPTIONS = AWS_COST_ANOMALY_DETECTION_ENDPOINTS["anomaly_subscriptions"]


def without_retry_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cast(Any, send_operation).retry, "wait", wait_none())


class FakeResumeManager(ResumableSourceManager[AwsCostAnomalyDetectionResumeConfig]):
    def __init__(self, state: Optional[AwsCostAnomalyDetectionResumeConfig] = None) -> None:
        self.state = state
        self.saved: list[AwsCostAnomalyDetectionResumeConfig] = []
        self.cleared = False

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[AwsCostAnomalyDetectionResumeConfig]:
        return self.state

    def save_state(self, data: AwsCostAnomalyDetectionResumeConfig) -> None:
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


def anomaly(anomaly_id: str = "anomaly-1", root_causes: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    return {
        "AnomalyId": anomaly_id,
        "AnomalyStartDate": "2024-05-01",
        "AnomalyEndDate": "2024-05-04T00:00:00Z",
        "DimensionValue": "AmazonS3",
        "MonitorArn": "arn:aws:ce::123456789012:anomalymonitor/abc",
        "Feedback": "PLANNED_ACTIVITY",
        "AnomalyScore": {"CurrentScore": 0.4, "MaxScore": 0.9},
        "Impact": {
            "MaxImpact": 40.5,
            "TotalImpact": 120.25,
            "TotalActualSpend": 220.25,
            "TotalExpectedSpend": 100.0,
            "TotalImpactPercentage": 120.25,
        },
        "RootCauses": root_causes if root_causes is not None else [],
    }


def anomalies_page(items: list[dict[str, Any]], next_page_token: Optional[str] = None) -> dict[str, Any]:
    body: dict[str, Any] = {"Anomalies": items}
    if next_page_token is not None:
        body["NextPageToken"] = next_page_token
    return body


class TestResolveDateIntervalStart:
    TODAY = dt.date(2024, 6, 1)

    def test_a_full_refresh_asks_for_the_whole_retention_window(self) -> None:
        assert resolve_date_interval_start(False, None, self.TODAY) == dt.date(2024, 3, 3)

    def test_a_watermark_is_ignored_when_the_run_is_not_incremental(self) -> None:
        assert resolve_date_interval_start(False, "2024-05-30", self.TODAY) == dt.date(2024, 3, 3)

    @pytest.mark.parametrize(
        "watermark",
        [
            "2024-05-20",
            "2024-05-20T09:30:00Z",
            dt.date(2024, 5, 20),
            dt.datetime(2024, 5, 20, 9, 30, tzinfo=dt.UTC),
        ],
    )
    def test_incremental_rewinds_behind_the_watermark_so_ongoing_anomalies_are_re_read(self, watermark: Any) -> None:
        assert resolve_date_interval_start(True, watermark, self.TODAY) == dt.date(2024, 5, 6)

    def test_incremental_never_reaches_past_the_ninety_day_retention_floor(self) -> None:
        assert resolve_date_interval_start(True, "2023-01-01", self.TODAY) == dt.date(2024, 3, 3)

    def test_a_watermark_in_the_future_is_clamped_to_today(self) -> None:
        assert resolve_date_interval_start(True, "2025-01-01", self.TODAY) == self.TODAY

    def test_an_unparseable_watermark_falls_back_to_the_retention_floor(self) -> None:
        assert resolve_date_interval_start(True, "not-a-date", self.TODAY) == dt.date(2024, 3, 3)


class TestBuildPayload:
    def test_anomalies_send_an_open_ended_date_interval(self) -> None:
        payload = build_payload(ANOMALIES, dt.date(2024, 3, 3), None)

        assert payload["MaxResults"] == ANOMALIES.page_size
        # An open anomaly has its end date pushed forward by AWS, so bounding the window with an
        # `EndDate` could drop it from the results.
        assert payload["DateInterval"] == {"StartDate": "2024-03-03"}
        assert "NextPageToken" not in payload

    def test_a_page_token_is_sent_back_under_the_key_aws_returned_it_in(self) -> None:
        assert build_payload(ANOMALIES, dt.date(2024, 3, 3), "tok")["NextPageToken"] == "tok"

    @pytest.mark.parametrize("endpoint_config", [MONITORS, SUBSCRIPTIONS])
    def test_operations_without_a_date_filter_never_send_a_date_interval(self, endpoint_config: Any) -> None:
        assert build_payload(endpoint_config, dt.date(2024, 3, 3), None) == {"MaxResults": endpoint_config.page_size}


class TestNormalizeRow:
    def test_anomaly_scores_and_impact_flatten_into_prefixed_columns(self) -> None:
        row = normalize_row(ANOMALIES, anomaly())

        assert row["anomaly_id"] == "anomaly-1"
        assert row["dimension_value"] == "AmazonS3"
        assert row["feedback"] == "PLANNED_ACTIVITY"
        assert row["anomaly_score_current_score"] == 0.4
        assert row["anomaly_score_max_score"] == 0.9
        assert row["impact_max_impact"] == 40.5
        assert row["impact_total_impact"] == 120.25
        assert row["impact_total_actual_spend"] == 220.25
        assert row["impact_total_expected_spend"] == 100.0
        assert row["impact_total_impact_percentage"] == 120.25

    @pytest.mark.parametrize(
        "column,expected",
        [
            ("anomaly_start_date", dt.datetime(2024, 5, 1, tzinfo=dt.UTC)),
            ("anomaly_end_date", dt.datetime(2024, 5, 4, tzinfo=dt.UTC)),
        ],
    )
    def test_both_date_only_and_timestamped_dates_parse_to_utc_datetimes(self, column: str, expected: Any) -> None:
        # The incremental cursor is a datetime column, so a bare `YYYY-MM-DD` has to parse too.
        assert normalize_row(ANOMALIES, anomaly())[column] == expected

    def test_root_causes_stay_a_list_with_their_own_fields_snake_cased(self) -> None:
        row = normalize_row(
            ANOMALIES,
            anomaly(
                root_causes=[
                    {
                        "Service": "AmazonS3",
                        "Region": "us-east-1",
                        "LinkedAccount": "123456789012",
                        "LinkedAccountName": "prod",
                        "UsageType": "USE1-TimedStorage-ByteHrs",
                        "Impact": {"Contribution": 88.5},
                    }
                ]
            ),
        )

        assert row["root_causes"] == [
            {
                "service": "AmazonS3",
                "region": "us-east-1",
                "linked_account": "123456789012",
                "linked_account_name": "prod",
                "usage_type": "USE1-TimedStorage-ByteHrs",
                "impact_contribution": 88.5,
            }
        ]

    def test_a_monitor_specification_is_kept_whole_rather_than_exploded_into_columns(self) -> None:
        # The keys inside it are the customer's own tag and cost category keys, so flattening
        # would mint a column per key and shift the table's schema per account.
        row = normalize_row(
            MONITORS,
            {
                "MonitorArn": "arn:aws:ce::123456789012:anomalymonitor/abc",
                "MonitorName": "Service monitor",
                "MonitorType": "DIMENSIONAL",
                "MonitorDimension": "SERVICE",
                "MonitorSpecification": {"Tags": {"Key": "team", "Values": ["growth"]}},
                "DimensionalValueCount": 12,
                "CreationDate": "2024-01-02T03:04:05Z",
                "LastUpdatedDate": "2024-02-01",
                "LastEvaluatedDate": "2024-06-01",
            },
        )

        assert row["monitor_specification"] == {"Tags": {"Key": "team", "Values": ["growth"]}}
        assert row["monitor_name"] == "Service monitor"
        assert row["dimensional_value_count"] == 12
        assert row["creation_date"] == dt.datetime(2024, 1, 2, 3, 4, 5, tzinfo=dt.UTC)
        assert row["last_updated_date"] == dt.datetime(2024, 2, 1, tzinfo=dt.UTC)
        assert row["last_evaluated_date"] == dt.datetime(2024, 6, 1, tzinfo=dt.UTC)

    def test_subscription_lists_survive_normalization(self) -> None:
        row = normalize_row(
            SUBSCRIPTIONS,
            {
                "SubscriptionArn": "arn:aws:ce::123456789012:anomalysubscription/def",
                "SubscriptionName": "Daily alerts",
                "AccountId": "123456789012",
                "MonitorArnList": ["arn:aws:ce::123456789012:anomalymonitor/abc"],
                "Subscribers": [{"Address": "finops@example.com", "Type": "EMAIL", "Status": "CONFIRMED"}],
                "Frequency": "DAILY",
                "Threshold": 100.0,
                "ThresholdExpression": {
                    "Dimensions": {"Key": "ANOMALY_TOTAL_IMPACT_ABSOLUTE", "Values": ["100"]},
                },
            },
        )

        assert row["monitor_arn_list"] == ["arn:aws:ce::123456789012:anomalymonitor/abc"]
        assert row["subscribers"] == [
            {"address": "finops@example.com", "type": "EMAIL", "status": "CONFIRMED"},
        ]
        assert row["threshold_expression"] == {
            "Dimensions": {"Key": "ANOMALY_TOTAL_IMPACT_ABSOLUTE", "Values": ["100"]}
        }
        assert row["threshold"] == 100.0

    def test_missing_members_do_not_invent_columns(self) -> None:
        row = normalize_row(ANOMALIES, {"AnomalyId": "anomaly-2", "MonitorArn": "arn"})

        assert row == {"anomaly_id": "anomaly-2", "monitor_arn": "arn"}


class TestErrorClassification:
    @pytest.mark.parametrize(
        "code",
        ["LimitExceededException", "ThrottlingException", "TooManyRequestsException", "RequestLimitExceeded"],
    )
    def test_throttling_codes_are_retryable(self, code: str) -> None:
        response = make_response(400, {"__type": f"com.amazon.coral.availability#{code}", "message": "slow down"})

        error = error_for_response(response)

        assert isinstance(error, AwsCostAnomalyDetectionThrottledError)
        assert f"AWS Cost Anomaly Detection request failed: {code}" in str(error)

    @pytest.mark.parametrize(
        "code",
        [
            "AccessDeniedException",
            "UnrecognizedClientException",
            "ExpiredTokenException",
            "DataUnavailableException",
            "InvalidNextTokenException",
        ],
    )
    def test_permanent_codes_are_not_retryable_and_stringify_for_the_source_mapping(self, code: str) -> None:
        response = make_response(400, {"__type": code, "message": "nope"})

        error = error_for_response(response)

        assert not isinstance(error, AwsCostAnomalyDetectionThrottledError)
        assert str(error) == f"AWS Cost Anomaly Detection request failed: {code} - nope"

    def test_the_error_type_header_wins_over_the_body(self) -> None:
        response = make_response(
            400,
            {"message": "nope"},
            headers={"x-amzn-ErrorType": "AccessDeniedException:http://internal.amazon.com/coral/"},
        )

        assert str(error_for_response(response)).startswith(
            "AWS Cost Anomaly Detection request failed: AccessDeniedException - nope"
        )

    def test_a_non_json_error_body_still_produces_a_usable_message(self) -> None:
        response = requests.Response()
        response.status_code = 503
        response._content = b"<html>gateway</html>"

        assert "HTTP 503" in str(error_for_response(response))


class TestSendOperation:
    def test_requests_are_sigv4_signed_against_us_east_1_and_dispatched_via_x_amz_target(self) -> None:
        session = mock.MagicMock(spec=requests.Session)
        session.post.return_value = make_response(200, {"Anomalies": []})
        credentials = aws_cost_anomaly_detection.Credentials("AKIAEXAMPLE", "secret")

        with freeze_time("2024-06-05T10:00:00Z"):
            send_operation(session, credentials, "GetAnomalies", {"MaxResults": 100})

        kwargs = session.post.call_args[1]
        assert session.post.call_args[0][0] == CE_ENDPOINT_URL
        assert kwargs["headers"]["X-Amz-Target"] == "AWSInsightsIndexService.GetAnomalies"
        assert kwargs["headers"]["Content-Type"] == "application/x-amz-json-1.1"
        # Cost Anomaly Detection is global: a request signed for any other region is rejected.
        assert kwargs["headers"]["Authorization"].startswith(
            "AWS4-HMAC-SHA256 Credential=AKIAEXAMPLE/20240605/us-east-1/ce/aws4_request"
        )
        assert json.loads(kwargs["data"]) == {"MaxResults": 100}

    def test_temporary_credentials_carry_the_session_token(self) -> None:
        session = mock.MagicMock(spec=requests.Session)
        session.post.return_value = make_response(200, {})
        credentials = aws_cost_anomaly_detection.Credentials("AKIAEXAMPLE", "secret", "session-token")

        send_operation(session, credentials, "GetAnomalies", {})

        assert session.post.call_args[1]["headers"]["X-Amz-Security-Token"] == "session-token"

    def test_throttled_calls_are_retried_until_they_succeed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        without_retry_backoff(monkeypatch)
        session = mock.MagicMock(spec=requests.Session)
        session.post.side_effect = [
            make_response(400, {"__type": "LimitExceededException", "message": "slow down"}),
            make_response(200, {"Anomalies": []}),
        ]

        body = send_operation(session, aws_cost_anomaly_detection.Credentials("k", "s"), "GetAnomalies", {})

        assert body == {"Anomalies": []}
        assert session.post.call_count == 2

    def test_permanent_errors_are_raised_without_retrying(self, monkeypatch: pytest.MonkeyPatch) -> None:
        without_retry_backoff(monkeypatch)
        session = mock.MagicMock(spec=requests.Session)
        session.post.return_value = make_response(400, {"__type": "AccessDeniedException", "message": "denied"})

        with pytest.raises(AwsCostAnomalyDetectionError):
            send_operation(session, aws_cost_anomaly_detection.Credentials("k", "s"), "GetAnomalies", {})

        assert session.post.call_count == 1


@freeze_time("2024-06-01T12:00:00Z")
class TestGetRows:
    def _run(
        self,
        responses: list[Any],
        manager: FakeResumeManager,
        endpoint: str = "anomalies",
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[list[dict[str, Any]]], mock.MagicMock]:
        with mock.patch.object(aws_cost_anomaly_detection, "send_operation", side_effect=responses) as send:
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

    def test_pagination_stops_when_aws_stops_returning_a_token(self) -> None:
        batches, send = self._run(
            [
                anomalies_page([anomaly("anomaly-1")], next_page_token="page-2"),
                anomalies_page([anomaly("anomaly-2")]),
            ],
            FakeResumeManager(),
        )

        assert send.call_count == 2
        assert [row["anomaly_id"] for batch in batches for row in batch] == ["anomaly-1", "anomaly-2"]
        assert "NextPageToken" not in send.call_args_list[0][0][3]
        assert send.call_args_list[1][0][3]["NextPageToken"] == "page-2"

    def test_state_is_saved_after_each_page_and_cleared_once_the_walk_completes(self) -> None:
        manager = FakeResumeManager()

        self._run([anomalies_page([anomaly()], next_page_token="page-2"), anomalies_page([])], manager)

        assert manager.saved == [
            AwsCostAnomalyDetectionResumeConfig(date_interval_start="2024-03-03", next_page_token="page-2"),
            AwsCostAnomalyDetectionResumeConfig(date_interval_start="2024-03-03", next_page_token=None),
        ]
        assert manager.cleared is True

    def test_a_saved_token_for_this_windows_start_resumes_mid_walk(self) -> None:
        manager = FakeResumeManager(
            AwsCostAnomalyDetectionResumeConfig(date_interval_start="2024-03-03", next_page_token="page-7")
        )

        _, send = self._run([anomalies_page([anomaly()])], manager)

        assert send.call_args_list[0][0][3]["NextPageToken"] == "page-7"

    def test_a_token_saved_for_a_different_window_restarts_the_walk(self) -> None:
        # The window start moves with the watermark, and a token only ever belongs to the window
        # it was issued for, so reusing it would skip the anomalies before it.
        manager = FakeResumeManager(
            AwsCostAnomalyDetectionResumeConfig(date_interval_start="2024-01-01", next_page_token="stale")
        )

        _, send = self._run([anomalies_page([anomaly()])], manager)

        assert "NextPageToken" not in send.call_args_list[0][0][3]
        assert send.call_args_list[0][0][3]["DateInterval"] == {"StartDate": "2024-03-03"}

    def test_an_expired_saved_token_restarts_the_walk_instead_of_failing_the_job(self) -> None:
        manager = FakeResumeManager(
            AwsCostAnomalyDetectionResumeConfig(date_interval_start="2024-03-03", next_page_token="expired")
        )

        batches, send = self._run(
            [
                AwsCostAnomalyDetectionError(
                    "AWS Cost Anomaly Detection request failed: InvalidNextTokenException - bad token"
                ),
                anomalies_page([anomaly("anomaly-1")]),
            ],
            manager,
        )

        assert send.call_count == 2
        assert "NextPageToken" not in send.call_args_list[1][0][3]
        assert [row["anomaly_id"] for batch in batches for row in batch] == ["anomaly-1"]

    def test_an_expired_token_error_on_a_fresh_walk_is_not_swallowed(self) -> None:
        with pytest.raises(AwsCostAnomalyDetectionError):
            self._run(
                [
                    AwsCostAnomalyDetectionError(
                        "AWS Cost Anomaly Detection request failed: InvalidNextTokenException - bad token"
                    )
                ],
                FakeResumeManager(),
            )

    @pytest.mark.parametrize(
        "should_use_incremental_field,watermark,expected_start",
        [
            (False, None, "2024-03-03"),
            (True, None, "2024-03-03"),
            (True, "2024-05-28", "2024-05-14"),
        ],
    )
    def test_the_requested_window_follows_the_watermark(
        self, should_use_incremental_field: bool, watermark: Any, expected_start: str
    ) -> None:
        _, send = self._run(
            [anomalies_page([])],
            FakeResumeManager(),
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=watermark,
        )

        assert send.call_args_list[0][0][3]["DateInterval"] == {"StartDate": expected_start}

    @pytest.mark.parametrize(
        "endpoint,result_key,identifier_column,identifier",
        [
            ("anomaly_monitors", "AnomalyMonitors", "monitor_arn", "arn:aws:ce::1:anomalymonitor/abc"),
            (
                "anomaly_subscriptions",
                "AnomalySubscriptions",
                "subscription_arn",
                "arn:aws:ce::1:anomalysubscription/def",
            ),
        ],
    )
    def test_the_undated_operations_send_no_date_interval(
        self, endpoint: str, result_key: str, identifier_column: str, identifier: str
    ) -> None:
        column = {"anomaly_monitors": "MonitorArn", "anomaly_subscriptions": "SubscriptionArn"}[endpoint]

        batches, send = self._run(
            [{result_key: [{column: identifier}]}],
            FakeResumeManager(),
            endpoint=endpoint,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-05-28",
        )

        assert "DateInterval" not in send.call_args_list[0][0][3]
        assert batches[0][0][identifier_column] == identifier

    def test_an_empty_page_yields_nothing_but_still_finishes_cleanly(self) -> None:
        manager = FakeResumeManager()

        batches, send = self._run([anomalies_page([])], manager)

        assert batches == []
        assert send.call_count == 1
        assert manager.cleared is True


class TestValidateCredentials:
    def test_missing_credentials_short_circuit_without_a_billed_request(self) -> None:
        with mock.patch.object(aws_cost_anomaly_detection, "send_operation") as send:
            assert validate_credentials("", "secret", None) == (
                False,
                "AWS access key ID and secret access key are required",
            )

        send.assert_not_called()

    def test_a_successful_probe_validates_against_the_cheapest_operation(self) -> None:
        with mock.patch.object(aws_cost_anomaly_detection, "send_operation", return_value={"AnomalyMonitors": []}) as s:
            assert validate_credentials("key", "secret", None) == (True, None)

        assert s.call_args[0][2] == "GetAnomalyMonitors"
        assert s.call_args[0][3] == {"MaxResults": 1}

    def test_a_denied_probe_still_creates_the_source_so_readable_tables_can_sync(self) -> None:
        error = AwsCostAnomalyDetectionError(
            "AWS Cost Anomaly Detection request failed: AccessDeniedException - not authorized"
        )

        with mock.patch.object(aws_cost_anomaly_detection, "send_operation", side_effect=error):
            assert validate_credentials("key", "secret", None) == (True, None)

    @pytest.mark.parametrize("code", ["DataUnavailableException", "BillExpirationException"])
    def test_an_account_without_cost_explorer_is_told_to_enable_it(self, code: str) -> None:
        error = AwsCostAnomalyDetectionError(f"AWS Cost Anomaly Detection request failed: {code} - no data")

        with mock.patch.object(aws_cost_anomaly_detection, "send_operation", side_effect=error):
            assert validate_credentials("key", "secret", None) == (False, ENABLEMENT_MESSAGE)

    def test_a_rejected_key_is_surfaced_to_the_user(self) -> None:
        error = AwsCostAnomalyDetectionError(
            "AWS Cost Anomaly Detection request failed: UnrecognizedClientException - invalid token"
        )

        with mock.patch.object(aws_cost_anomaly_detection, "send_operation", side_effect=error):
            assert validate_credentials("key", "secret", None) == (False, str(error))

    def test_a_transport_failure_does_not_leak_internals(self) -> None:
        with mock.patch.object(
            aws_cost_anomaly_detection, "send_operation", side_effect=requests.ConnectionError("boom")
        ):
            assert validate_credentials("key", "secret", None) == (False, "Could not reach the AWS Cost Explorer API")

    @freeze_time("2024-06-01T12:00:00Z")
    def test_a_per_schema_check_probes_that_schemas_own_operation(self) -> None:
        with mock.patch.object(aws_cost_anomaly_detection, "send_operation", return_value={"Anomalies": []}) as send:
            assert validate_credentials("key", "secret", None, schema_name="anomalies") == (True, None)

        assert send.call_args[0][2] == "GetAnomalies"
        # `DateInterval` is required, so the probe has to send one or AWS rejects the call.
        assert send.call_args[0][3]["DateInterval"] == {"StartDate": "2024-05-31"}

    def test_a_per_schema_check_reports_the_missing_iam_permission(self) -> None:
        error = AwsCostAnomalyDetectionError(
            "AWS Cost Anomaly Detection request failed: AccessDeniedException - "
            "User is not authorized to perform ce:GetAnomalies"
        )

        with mock.patch.object(aws_cost_anomaly_detection, "send_operation", side_effect=error):
            assert validate_credentials("key", "secret", None, schema_name="anomalies") == (
                False,
                "Missing IAM permission ce:GetAnomalies",
            )


class TestProbeEndpointPermissions:
    def test_reachable_endpoints_report_no_reason(self) -> None:
        with mock.patch.object(aws_cost_anomaly_detection, "send_operation", return_value={}):
            assert probe_endpoint_permissions("key", "secret", None, list(AWS_COST_ANOMALY_DETECTION_ENDPOINTS)) == {
                "anomalies": None,
                "anomaly_monitors": None,
                "anomaly_subscriptions": None,
            }

    def test_a_denial_names_the_permission_to_grant(self) -> None:
        error = AwsCostAnomalyDetectionError(
            "AWS Cost Anomaly Detection request failed: AccessDeniedException - "
            "User is not authorized to perform ce:GetAnomalySubscriptions"
        )

        with mock.patch.object(aws_cost_anomaly_detection, "send_operation", side_effect=error):
            reasons = probe_endpoint_permissions("key", "secret", None, ["anomaly_subscriptions"])

        assert reasons == {"anomaly_subscriptions": "Missing IAM permission ce:GetAnomalySubscriptions"}

    @pytest.mark.parametrize(
        "error",
        [
            AwsCostAnomalyDetectionThrottledError(
                "AWS Cost Anomaly Detection request failed: LimitExceededException - slow down"
            ),
            requests.ConnectionError("boom"),
        ],
    )
    def test_a_throttle_or_network_blip_never_hides_a_table_from_the_picker(self, error: Exception) -> None:
        with mock.patch.object(aws_cost_anomaly_detection, "send_operation", side_effect=error):
            assert probe_endpoint_permissions("key", "secret", None, ["anomalies"]) == {"anomalies": None}

    def test_an_unknown_endpoint_name_is_reported_as_reachable_rather_than_raising(self) -> None:
        with mock.patch.object(aws_cost_anomaly_detection, "send_operation", return_value={}) as send:
            assert probe_endpoint_permissions("key", "secret", None, ["not_a_table"]) == {"not_a_table": None}

        send.assert_not_called()
