import json
import datetime as dt
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_cloudwatch.amazon_cloudwatch import (
    GENERIC_VALIDATION_ERROR,
    MAX_ATTEMPTS,
    TRANSIENT_VALIDATION_ERROR,
    VALIDATION_ERROR_MESSAGES,
    AmazonCloudWatchResumeConfig,
    parse_metric_queries,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.amazon_cloudwatch.source import (
    AmazonCloudWatchSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.responders import UnexpectedRequest
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.amazoncloudwatch import (
    AmazonCloudWatchSourceConfig,
)

NOW = "2024-03-10T12:00:00Z"
LOGS_ORIGIN = "https://logs.us-east-1.amazonaws.com"
MONITORING_ORIGIN = "https://monitoring.us-east-1.amazonaws.com"
XMLNS = "http://monitoring.amazonaws.com/doc/2010-08-01/"


def config(**overrides: Any) -> AmazonCloudWatchSourceConfig:
    values: dict[str, Any] = {
        "aws_access_key_id": "AKIAEXAMPLE",
        "aws_secret_access_key": "secret",
        "aws_session_token": None,
        "aws_region": "us-east-1",
        "log_group_names": "/aws/lambda/one\n/aws/lambda/two\n",
        "metric_queries": None,
        "start_date": "2024-03-08",
    }
    values.update(overrides)
    return AmazonCloudWatchSourceConfig(**values)


def driver(**overrides: Any) -> SourceDriver:
    return SourceDriver(AmazonCloudWatchSource(), config(**overrides))


def by_origin(**queues: list[ScriptedResponse]) -> Callable[[RecordedRequest], ScriptedResponse]:
    """Both AWS APIs post to `/`, so answers are routed by host rather than by path."""
    table = {"logs": queues.get("logs", []), "monitoring": queues.get("monitoring", [])}

    def respond(request: RecordedRequest) -> ScriptedResponse:
        queue = table["logs"] if request.origin == LOGS_ORIGIN else table["monitoring"]
        if not queue:
            raise UnexpectedRequest(f"no answer left for {request.method} {request.url}")
        return queue.pop(0)

    return respond


def logs_page(events: list[dict[str, Any]], next_token: str | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"events": events, "searchedLogStreams": []}
    if next_token:
        body["nextToken"] = next_token
    return ScriptedResponse(json=body)


def event(event_id: str, timestamp: int = 1709900000000) -> dict[str, Any]:
    return {
        "eventId": event_id,
        "timestamp": timestamp,
        "ingestionTime": timestamp + 5,
        "message": "m",
        "logStreamName": "s",
    }


def xml_response(action: str, result_xml: str, status: int = 200) -> ScriptedResponse:
    body = (
        f'<{action}Response xmlns="{XMLNS}"><{action}Result>{result_xml}</{action}Result>'
        f"<ResponseMetadata><RequestId>r</RequestId></ResponseMetadata></{action}Response>"
    )
    return ScriptedResponse(status=status, body=body.encode(), headers={"Content-Type": "text/xml"})


CALLER_IDENTITY = ScriptedResponse(
    body=(
        b'<GetCallerIdentityResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/"><GetCallerIdentityResult>'
        b"<Arn>arn:aws:iam::000000000000:user/example</Arn><UserId>AIDAEXAMPLE</UserId><Account>000000000000</Account>"
        b"</GetCallerIdentityResult><ResponseMetadata><RequestId>r</RequestId></ResponseMetadata></GetCallerIdentityResponse>"
    ),
    headers={"Content-Type": "text/xml"},
)


def xml_error(code: str, message: str, status: int = 400) -> ScriptedResponse:
    body = f'<ErrorResponse xmlns="{XMLNS}"><Error><Type>Sender</Type><Code>{code}</Code><Message>{message}</Message></Error><RequestId>r</RequestId></ErrorResponse>'
    return ScriptedResponse(status=status, body=body.encode(), headers={"Content-Type": "text/xml"})


def metric_result(query_id: str, points: list[tuple[str, float]], label: str = "CPUUtilization") -> str:
    timestamps = "".join(f"<member>{ts}</member>" for ts, _ in points)
    values = "".join(f"<member>{value}</member>" for _, value in points)
    return (
        f"<member><Id>{query_id}</Id><Label>{label}</Label><Timestamps>{timestamps}</Timestamps>"
        f"<Values>{values}</Values><StatusCode>Complete</StatusCode></member>"
    )


def form(request: RecordedRequest) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs((request.body or b"").decode()).items()}


@pytest.fixture(autouse=True)
def _frozen_clock():
    with time_machine.travel(NOW, tick=False):
        yield


class TestLogEvents:
    def test_walks_every_page_of_each_log_group_and_stages_the_cursor_before_the_batch(self) -> None:
        result = driver().run(
            "log_events",
            by_origin(
                logs=[
                    logs_page([event("a1")], next_token="p2"),
                    logs_page([], next_token="p3"),
                    logs_page([event("a2")]),
                    logs_page([event("b1")]),
                ]
            ),
        )

        assert result.raised is None
        assert [request.headers["x-amz-target"] for request in result.requests] == ["Logs_20140328.FilterLogEvents"] * 4
        bodies = [request.json() for request in result.requests]
        assert [(body["logGroupName"], body.get("nextToken")) for body in bodies] == [
            ("/aws/lambda/one", None),
            ("/aws/lambda/one", "p2"),
            ("/aws/lambda/one", "p3"),
            ("/aws/lambda/two", None),
        ]
        assert bodies[0]["startTime"] == int(dt.datetime(2024, 3, 8, tzinfo=dt.UTC).timestamp() * 1000)
        assert bodies[0]["endTime"] == int(dt.datetime(2024, 3, 10, 12, tzinfo=dt.UTC).timestamp() * 1000)
        assert [row["event_id"] for row in result.rows] == ["a1", "a2", "b1"]
        assert result.rows[0]["log_group_name"] == "/aws/lambda/one"
        assert result.rows[0]["timestamp"] == dt.datetime(2024, 3, 8, 12, 13, 20, tzinfo=dt.UTC)
        # The cursor staged with the first page points at the second page, and persisted with it.
        first_cursor = AmazonCloudWatchResumeConfig(
            slice_key="/aws/lambda/one",
            next_token="p2",
            window_start="2024-03-08T00:00:00+00:00",
            window_end="2024-03-10T12:00:00+00:00",
        )
        assert result.saved_states[0] == first_cursor
        assert result.committed_states[0] == first_cursor
        # The last page of a group stages the next group, so a handoff there does not reread the group.
        assert result.saved_states[2] == AmazonCloudWatchResumeConfig(
            slice_key="/aws/lambda/two",
            next_token=None,
            window_start="2024-03-08T00:00:00+00:00",
            window_end="2024-03-10T12:00:00+00:00",
        )
        assert result.saved_states[3].slice_key == "__complete__"
        assert result.final_state is None
        # Events arrive per log group, so the watermark may only move once the whole run completes.
        assert result.response is not None and result.response.sort_mode == "desc"

    def test_resumes_at_the_saved_log_group_and_page(self) -> None:
        result = driver().run(
            "log_events",
            by_origin(logs=[logs_page([event("b2")])]),
            resume_state=AmazonCloudWatchResumeConfig(slice_key="/aws/lambda/two", next_token="p9"),
        )

        assert result.raised is None
        assert [(r.json()["logGroupName"], r.json().get("nextToken")) for r in result.requests] == [
            ("/aws/lambda/two", "p9")
        ]

    def test_a_cursor_staged_after_the_last_page_ends_the_run_without_a_request(self) -> None:
        result = driver().run(
            "log_events",
            by_origin(),
            resume_state=AmazonCloudWatchResumeConfig(
                slice_key="__complete__",
                window_start="2024-03-08T00:00:00+00:00",
                window_end="2024-03-10T12:00:00+00:00",
            ),
        )

        assert result.raised is None
        assert result.requests == []
        assert result.final_state is None

    def test_a_saved_log_group_no_longer_configured_restarts_from_the_first_group(self) -> None:
        result = driver().run(
            "log_events",
            by_origin(logs=[logs_page([]), logs_page([])]),
            resume_state=AmazonCloudWatchResumeConfig(slice_key="/aws/lambda/gone", next_token="p9"),
        )

        assert result.raised is None
        assert [r.json()["logGroupName"] for r in result.requests] == ["/aws/lambda/one", "/aws/lambda/two"]
        assert all("nextToken" not in r.json() for r in result.requests)

    @pytest.mark.parametrize(
        ("start_date", "incremental_field", "watermark", "expected_start"),
        [
            (
                "2024-03-08",
                "timestamp",
                dt.datetime(2024, 3, 9, 6, tzinfo=dt.UTC),
                dt.datetime(2024, 3, 9, 6, tzinfo=dt.UTC),
            ),
            # A watermark older than the configured start date never widens the window.
            ("2024-03-08", "timestamp", dt.datetime(2024, 1, 1, tzinfo=dt.UTC), dt.datetime(2024, 3, 8, tzinfo=dt.UTC)),
            ("2024-03-08", None, None, dt.datetime(2024, 3, 8, tzinfo=dt.UTC)),
            # The 7-day default only bounds a first run. After a longer pause the gap is still read.
            ("", "timestamp", dt.datetime(2024, 2, 20, tzinfo=dt.UTC), dt.datetime(2024, 2, 20, tzinfo=dt.UTC)),
            ("", None, None, dt.datetime(2024, 3, 3, 12, tzinfo=dt.UTC)),
        ],
    )
    def test_an_incremental_run_starts_at_the_watermark(
        self,
        start_date: str,
        incremental_field: str | None,
        watermark: dt.datetime | None,
        expected_start: dt.datetime,
    ) -> None:
        result = driver(log_group_names="/aws/lambda/one", start_date=start_date).run(
            "log_events",
            by_origin(logs=[logs_page([])]),
            incremental_field=incremental_field,
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        assert result.requests[0].json()["startTime"] == int(expected_start.timestamp() * 1000)

    def test_no_configured_log_groups_discovers_them_first(self) -> None:
        result = driver(log_group_names="").run(
            "log_events",
            by_origin(
                logs=[
                    ScriptedResponse(
                        json={
                            "logGroups": [
                                {"logGroupName": "/discovered"},
                                # FilterLogEvents rejects these classes, which would fail the whole table.
                                {"logGroupName": "/infrequent", "logGroupClass": "INFREQUENT_ACCESS"},
                                {"logGroupName": "/delivery", "logGroupClass": "DELIVERY"},
                            ]
                        }
                    ),
                    logs_page([event("d1")]),
                ]
            ),
        )

        assert result.raised is None
        assert [r.headers["x-amz-target"] for r in result.requests] == [
            "Logs_20140328.DescribeLogGroups",
            "Logs_20140328.FilterLogEvents",
        ]
        assert result.requests[1].json()["logGroupName"] == "/discovered"

    def test_a_missing_log_group_fails_the_run_with_the_aws_code(self) -> None:
        result = driver(log_group_names="/aws/lambda/one").run(
            "log_events",
            by_origin(
                logs=[
                    ScriptedResponse(
                        status=400,
                        headers={"x-amzn-ErrorType": "ResourceNotFoundException"},
                        json={
                            "__type": "ResourceNotFoundException",
                            "message": "The specified log group does not exist.",
                        },
                    )
                ]
            ),
        )

        assert result.raised is not None
        assert str(result.raised).startswith("Amazon CloudWatch request failed: ResourceNotFoundException")


class TestLogGroups:
    def test_converts_creation_time_and_follows_next_token(self) -> None:
        result = driver().run(
            "log_groups",
            by_origin(
                logs=[
                    ScriptedResponse(
                        json={
                            "logGroups": [{"logGroupName": "/a", "creationTime": 1709900000000, "storedBytes": 10}],
                            "nextToken": "n2",
                        }
                    ),
                    ScriptedResponse(json={"logGroups": [{"logGroupName": "/b", "creationTime": 1709900000000}]}),
                ]
            ),
        )

        assert result.raised is None
        assert [r.json().get("nextToken") for r in result.requests] == [None, "n2"]
        assert result.rows[0] == {
            "log_group_name": "/a",
            "creation_time": dt.datetime(2024, 3, 8, 12, 13, 20, tzinfo=dt.UTC),
            "stored_bytes": 10,
        }
        assert [row["log_group_name"] for row in result.rows] == ["/a", "/b"]


class TestMetricData:
    QUERIES = json.dumps(
        [
            {
                "id": "cpu",
                "namespace": "AWS/EC2",
                "metric_name": "CPUUtilization",
                "dimensions": {"InstanceId": "i-1"},
                "stat": "Average",
                "period": 300,
            },
            {"Id": "errors", "Expression": "SUM(METRICS())", "Period": 60},
        ]
    )

    def test_sends_the_queries_as_a_signed_form_request_and_reads_the_xml_datapoints(self) -> None:
        result = driver(metric_queries=self.QUERIES, start_date="2024-03-09").run(
            "metric_data",
            by_origin(
                monitoring=[
                    xml_response(
                        "GetMetricData",
                        "<MetricDataResults>"
                        + metric_result("cpu", [("2024-03-09T00:00:00Z", 1.5), ("2024-03-09T00:05:00Z", 2.0)])
                        + metric_result("errors", [("2024-03-09T00:00:00Z", 3)], label="errors")
                        + "</MetricDataResults><NextToken>tok2</NextToken>",
                    ),
                    xml_response("GetMetricData", "<MetricDataResults></MetricDataResults>"),
                ]
            ),
        )

        assert result.raised is None
        assert [r.origin for r in result.requests] == [MONITORING_ORIGIN] * 2
        first = form(result.requests[0])
        assert first["Action"] == "GetMetricData"
        assert first["Version"] == "2010-08-01"
        assert first["ScanBy"] == "TimestampAscending"
        assert first["StartTime"] == "2024-03-09T00:00:00Z"
        assert first["EndTime"] == "2024-03-10T12:00:00Z"
        assert first["MetricDataQueries.member.1.Id"] == "cpu"
        assert first["MetricDataQueries.member.1.MetricStat.Metric.Dimensions.member.1.Value"] == "i-1"
        assert first["MetricDataQueries.member.1.MetricStat.Period"] == "300"
        assert first["MetricDataQueries.member.2.Expression"] == "SUM(METRICS())"
        assert "NextToken" not in first
        assert form(result.requests[1])["NextToken"] == "tok2"
        assert "authorization" in result.requests[0].headers
        assert result.rows == [
            {
                "query_id": "cpu",
                "label": "CPUUtilization",
                "timestamp": dt.datetime(2024, 3, 9, 0, 0, tzinfo=dt.UTC),
                "value": 1.5,
                "status_code": "Complete",
            },
            {
                "query_id": "cpu",
                "label": "CPUUtilization",
                "timestamp": dt.datetime(2024, 3, 9, 0, 5, tzinfo=dt.UTC),
                "value": 2.0,
                "status_code": "Complete",
            },
            {
                "query_id": "errors",
                "label": "errors",
                "timestamp": dt.datetime(2024, 3, 9, 0, 0, tzinfo=dt.UTC),
                "value": 3.0,
                "status_code": "Complete",
            },
        ]

    @pytest.mark.parametrize(
        ("resume_state", "expected_windows"),
        [
            (
                None,
                [
                    ("2024-02-01T00:00:00Z", "2024-02-15T00:00:00Z"),
                    ("2024-02-15T00:00:00Z", "2024-02-29T00:00:00Z"),
                    ("2024-02-29T00:00:00Z", "2024-03-10T12:00:00Z"),
                ],
            ),
            (
                AmazonCloudWatchResumeConfig(slice_key="2024-02-29T00:00:00+00:00", next_token=None),
                [("2024-02-29T00:00:00Z", "2024-03-10T12:00:00Z")],
            ),
            # The attempt that saved this cursor started earlier, so its range differs from one
            # computed now. The resumed attempt keeps the saved range and its windows.
            (
                AmazonCloudWatchResumeConfig(
                    slice_key="2024-02-20T00:00:00+00:00",
                    next_token="tok7",
                    window_start="2024-02-06T00:00:00+00:00",
                    window_end="2024-03-05T00:00:00+00:00",
                ),
                [("2024-02-20T00:00:00Z", "2024-03-05T00:00:00Z")],
            ),
        ],
    )
    def test_a_long_range_is_split_into_windows_and_a_saved_window_resumes_there(
        self, resume_state: AmazonCloudWatchResumeConfig | None, expected_windows: list[tuple[str, str]]
    ) -> None:
        empty = xml_response("GetMetricData", "<MetricDataResults></MetricDataResults>")
        result = driver(metric_queries=self.QUERIES, start_date="2024-02-01").run(
            "metric_data",
            by_origin(monitoring=[empty, empty, empty]),
            resume_state=resume_state,
        )

        assert result.raised is None
        assert [(form(r)["StartTime"], form(r)["EndTime"]) for r in result.requests] == expected_windows

    def test_each_window_asks_for_a_period_that_cloudwatch_still_keeps_for_data_that_old(self) -> None:
        queries = json.dumps([{"id": "cpu", "namespace": "AWS/EC2", "metric_name": "CPUUtilization", "period": 60}])
        empty = xml_response("GetMetricData", "<MetricDataResults></MetricDataResults>")
        result = driver(metric_queries=queries, start_date="2023-12-20").run("metric_data", always(empty))

        assert result.raised is None
        assert [
            (form(r)["StartTime"][:10], form(r)["MetricDataQueries.member.1.MetricStat.Period"])
            for r in result.requests
        ] == [
            ("2023-12-20", "3600"),
            ("2024-01-03", "3600"),
            ("2024-01-17", "300"),
            ("2024-01-31", "300"),
            ("2024-02-14", "300"),
            ("2024-02-28", "60"),
        ]

    @pytest.mark.parametrize(
        ("status", "message"),
        [
            (
                "Forbidden",
                "Amazon CloudWatch request failed: MetricQueryForbidden - metric query 'cpu': Access denied",
            ),
            (
                "InternalError",
                "Amazon CloudWatch request failed: MetricQueryInternalError - metric query 'cpu': Access denied",
            ),
            # Partial data with no continuation token cannot be completed, so the run must not end as a success.
            (
                "PartialData",
                "Amazon CloudWatch request failed: MetricQueryPartialData - metric query 'cpu' returned more "
                "datapoints than one response holds",
            ),
        ],
    )
    def test_a_query_failing_inside_a_successful_response_fails_the_run(self, status: str, message: str) -> None:
        failed = (
            "<member><Id>cpu</Id><Label>CPUUtilization</Label><Timestamps></Timestamps><Values></Values>"
            f"<StatusCode>{status}</StatusCode><Messages><member><Code>{status}</Code><Value>Access denied</Value></member></Messages></member>"
        )
        result = driver(metric_queries=self.QUERIES).run(
            "metric_data",
            by_origin(monitoring=[xml_response("GetMetricData", f"<MetricDataResults>{failed}</MetricDataResults>")]),
        )

        assert str(result.raised) == message
        # The failing page's cursor was never staged, so a retry asks for the same page again.
        assert result.saved_states == []

    def test_without_queries_nothing_is_requested(self) -> None:
        result = driver(metric_queries="  ").run("metric_data", by_origin())

        assert result.raised is None
        assert result.requests == []
        assert result.rows == []

    def test_an_aws_error_in_the_xml_body_fails_the_run_with_its_code(self) -> None:
        result = driver(metric_queries=self.QUERIES).run(
            "metric_data",
            by_origin(monitoring=[xml_error("InvalidParameterValue", "The value of Period is invalid.")]),
        )

        assert result.raised is not None
        assert str(result.raised) == (
            "Amazon CloudWatch request failed: InvalidParameterValue - The value of Period is invalid."
        )

    def test_a_throttled_call_is_retried_until_it_succeeds(self) -> None:
        result = driver(metric_queries=self.QUERIES).run(
            "metric_data",
            by_origin(
                monitoring=[
                    xml_error("Throttling", "Rate exceeded"),
                    xml_response("GetMetricData", "<MetricDataResults></MetricDataResults>"),
                ]
            ),
        )

        assert result.raised is None
        assert len(result.requests) == 2


class TestAlarms:
    def test_metric_and_composite_alarms_land_in_one_table_tagged_by_type(self) -> None:
        result = driver().run(
            "alarms",
            by_origin(
                monitoring=[
                    xml_response(
                        "DescribeAlarms",
                        "<MetricAlarms><member><AlarmName>cpu-high</AlarmName><AlarmArn>arn:1</AlarmArn>"
                        "<StateValue>OK</StateValue><Threshold>80.0</Threshold>"
                        "<Dimensions><member><Name>InstanceId</Name><Value>i-1</Value></member></Dimensions>"
                        "</member></MetricAlarms><CompositeAlarms><member><AlarmName>site-down</AlarmName>"
                        "<AlarmArn>arn:2</AlarmArn><AlarmRule>ALARM(cpu-high)</AlarmRule></member></CompositeAlarms>"
                        "<NextToken>n2</NextToken>",
                    ),
                    xml_response("DescribeAlarms", "<MetricAlarms></MetricAlarms><CompositeAlarms></CompositeAlarms>"),
                ]
            ),
        )

        assert result.raised is None
        first = form(result.requests[0])
        assert first["Action"] == "DescribeAlarms"
        assert {first["AlarmTypes.member.1"], first["AlarmTypes.member.2"]} == {"CompositeAlarm", "MetricAlarm"}
        assert form(result.requests[1])["NextToken"] == "n2"
        assert [(row["alarm_arn"], row["alarm_type"]) for row in result.rows] == [
            ("arn:1", "MetricAlarm"),
            ("arn:2", "CompositeAlarm"),
        ]
        assert result.rows[0]["threshold"] == 80.0
        assert result.rows[0]["dimensions"] == [{"Name": "InstanceId", "Value": "i-1"}]
        assert result.rows[1]["alarm_rule"] == "ALARM(cpu-high)"


class TestAlarmHistory:
    def test_an_incremental_run_asks_for_history_after_the_watermark_in_ascending_order(self) -> None:
        result = driver().run(
            "alarm_history",
            by_origin(
                monitoring=[
                    xml_response(
                        "DescribeAlarmHistory",
                        "<AlarmHistoryItems>"
                        + "".join(
                            "<member><AlarmName>cpu-high</AlarmName><AlarmType>MetricAlarm</AlarmType>"
                            "<Timestamp>2024-03-09T08:00:00.123Z</Timestamp>"
                            "<HistoryItemType>AlarmContributorStateUpdate</HistoryItemType>"
                            f"<AlarmContributorId>{contributor}</AlarmContributorId>"
                            '<HistorySummary>Alarm updated from OK to ALARM</HistorySummary><HistoryData>{"x":1}</HistoryData>'
                            "</member>"
                            for contributor in ("c1", "c2")
                        )
                        + "</AlarmHistoryItems>",
                    )
                ]
            ),
            incremental_field="timestamp",
            db_incremental_field_last_value=dt.datetime(2024, 3, 9, 6, tzinfo=dt.UTC),
        )

        assert result.raised is None
        params = form(result.requests[0])
        assert params["Action"] == "DescribeAlarmHistory"
        assert params["StartDate"] == "2024-03-09T06:00:00Z"
        assert params["EndDate"] == "2024-03-10T12:00:00Z"
        assert params["ScanBy"] == "TimestampAscending"
        # An alarm with contributors records one item per contributor at the same instant.
        assert len({row.pop("history_id") for row in result.rows}) == 2
        assert result.rows == [
            {
                "alarm_name": "cpu-high",
                "alarm_type": "MetricAlarm",
                "timestamp": dt.datetime(2024, 3, 9, 8, 0, 0, 123000, tzinfo=dt.UTC),
                "history_item_type": "AlarmContributorStateUpdate",
                "alarm_contributor_id": contributor,
                "history_summary": "Alarm updated from OK to ALARM",
                "history_data": '{"x":1}',
            }
            for contributor in ("c1", "c2")
        ]
        assert result.response is not None and result.response.sort_mode == "asc"


class TestParseMetricQueries:
    def test_flat_queries_become_metric_data_queries(self) -> None:
        assert parse_metric_queries(
            '[{"namespace": "AWS/S3", "metric_name": "BucketSizeBytes", "dimensions": [{"name": "BucketName", "value": "b"}], "unit": "Bytes", "label": "size"}]'
        ) == [
            {
                "Id": "q1",
                "MetricStat": {
                    "Metric": {
                        "Namespace": "AWS/S3",
                        "MetricName": "BucketSizeBytes",
                        "Dimensions": [{"Name": "BucketName", "Value": "b"}],
                    },
                    "Period": 300,
                    "Stat": "Average",
                    "Unit": "Bytes",
                },
                "Label": "size",
                "ReturnData": True,
            }
        ]

    @pytest.mark.parametrize(
        ("raw", "message"),
        [
            ("not json", "Invalid metric queries: not valid JSON"),
            ('{"id": "a"}', "Invalid metric queries: query 1 needs a namespace and a metric_name"),
            (
                '[{"id": "a", "expression": "x"}, {"id": "a", "expression": "y"}]',
                "Invalid metric queries: the id 'a' is used twice",
            ),
            ("[1]", "Invalid metric queries: expected a JSON list"),
            (
                '[{"namespace": "AWS/EC2", "metric_name": "CPU", "dimensions": [1]}]',
                "Invalid metric queries: query 1 has a dimension without a name and a value",
            ),
            (
                '[{"namespace": "AWS/EC2", "metric_name": "CPU", "period": "five"}]',
                "Invalid metric queries: query 1 has a period that is not a whole number",
            ),
            ('[{"Id": "q1", "MetricStat": "invalid"}]', "Invalid metric queries: they do not match the CloudWatch API"),
        ],
    )
    def test_bad_queries_raise_a_message_for_the_wizard(self, raw: str, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            parse_metric_queries(raw)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("overrides", "expected"),
        [
            ({"aws_access_key_id": ""}, "AWS access key ID and secret access key are required"),
            ({"aws_region": "mars"}, "Enter an AWS region code, for example us-east-1."),
            (
                {"metric_queries": "{"},
                "Invalid metric queries: not valid JSON (Expecting property name enclosed in double quotes: line 1 column 2 (char 1)).",
            ),
            # Falling back to the default range would drop the history the user asked for.
            ({"start_date": "2024-02-30"}, "Invalid start date: enter it as YYYY-MM-DD, for example 2024-01-31."),
        ],
    )
    def test_local_checks_fail_before_any_request(self, overrides: dict[str, Any], expected: str) -> None:
        c = config(**overrides)

        with scripted_network([]) as network:
            assert validate_credentials(
                c.aws_access_key_id,
                c.aws_secret_access_key,
                c.aws_session_token,
                c.aws_region,
                c.metric_queries,
                c.start_date,
            ) == (False, expected)

        assert network.requests == 0

    @pytest.mark.parametrize(
        ("response", "expected"),
        [
            (CALLER_IDENTITY, (True, None)),
            (
                xml_error("InvalidClientTokenId", "The security token included in the request is invalid."),
                (False, VALIDATION_ERROR_MESSAGES["InvalidClientTokenId"]),
            ),
            (
                xml_error("SignatureDoesNotMatch", "The request signature we calculated does not match."),
                (False, VALIDATION_ERROR_MESSAGES["SignatureDoesNotMatch"]),
            ),
            (xml_error("SomethingNewException", "?"), (False, GENERIC_VALIDATION_ERROR)),
        ],
    )
    def test_the_probe_result_is_translated_and_never_echoes_the_aws_text(
        self, response: ScriptedResponse, expected: tuple[bool, str | None]
    ) -> None:
        c = config()

        with scripted_network([response]) as network:
            assert (
                validate_credentials(
                    c.aws_access_key_id, c.aws_secret_access_key, c.aws_session_token, c.aws_region, c.metric_queries
                )
                == expected
            )

        # STS answers any valid key without an IAM permission, so a key scoped to one table connects.
        probe = network.requests_log[0]
        assert probe.origin == "https://sts.us-east-1.amazonaws.com"
        assert b"Action=GetCallerIdentity" in (probe.body or b"")

    def test_a_china_region_is_reached_through_its_own_partition(self) -> None:
        c = config(aws_region="cn-north-1")

        with scripted_network([CALLER_IDENTITY]) as network:
            assert validate_credentials(
                c.aws_access_key_id, c.aws_secret_access_key, c.aws_session_token, c.aws_region, c.metric_queries
            ) == (True, None)

        assert network.requests_log[0].origin == "https://sts.cn-north-1.amazonaws.com.cn"

    @pytest.mark.parametrize(
        "response",
        [
            xml_error("Throttling", "Rate exceeded"),
            # A load balancer error page: botocore cannot parse it, and it carries no AWS code.
            ScriptedResponse(
                status=503, body=b"<html>Service Unavailable</html>", headers={"Content-Type": "text/html"}
            ),
        ],
    )
    def test_a_throttled_or_unavailable_probe_asks_the_user_to_retry(self, response: ScriptedResponse) -> None:
        c = config()

        with scripted_network(lambda _request: response) as network:
            assert validate_credentials(
                c.aws_access_key_id, c.aws_secret_access_key, c.aws_session_token, c.aws_region, c.metric_queries
            ) == (False, TRANSIENT_VALIDATION_ERROR)

        assert 1 < network.requests <= MAX_ATTEMPTS
