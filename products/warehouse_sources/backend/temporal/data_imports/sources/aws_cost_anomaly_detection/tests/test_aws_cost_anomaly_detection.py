import json
import datetime as dt
from typing import Any, Optional, cast

import pytest
import time_machine
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
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

LOGGER = structlog.get_logger()

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

    def test_an_unparseable_watermark_falls_back_to_the_retention_floor(self) -> None:
        assert resolve_date_interval_start(True, "not-a-date", self.TODAY) == dt.date(2024, 3, 3)


class TestBuildPayload:
    @pytest.mark.parametrize("endpoint_config", [MONITORS, SUBSCRIPTIONS])
    def test_operations_without_a_date_filter_never_send_a_date_interval(self, endpoint_config: Any) -> None:
        assert build_payload(endpoint_config, dt.date(2024, 3, 3), None) == {"MaxResults": endpoint_config.page_size}


class TestNormalizeRow:
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


class TestErrorClassification:
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


class TestGetRows:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel("2024-06-01T12:00:00Z", tick=False):
            yield

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
