from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.logs.backend.tasks.clickhouse_lag_metrics import (
    LAST_INSERT_AGE_METRIC,
    NEWEST_RECORD_AGE_METRIC,
    build_otlp_payload,
    logs_clickhouse_lag_metrics_task,
)

NOW_NANOS = 1_700_000_060_000_000_000

TASK_MODULE = "products.logs.backend.tasks.clickhouse_lag_metrics"


class TestClickhouseLagMetrics(SimpleTestCase):
    def test_payload_maps_rows_to_gauge_data_points(self) -> None:
        rows = [("clickhouse_logs", 3, 12, 45), ("clickhouse_traces", 0, 700, 900)]

        payload = build_otlp_payload(rows, NOW_NANOS)

        metrics = {m["name"]: m for m in payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]}
        assert set(metrics) == {LAST_INSERT_AGE_METRIC, NEWEST_RECORD_AGE_METRIC}

        insert_points = metrics[LAST_INSERT_AGE_METRIC]["gauge"]["dataPoints"]
        assert len(insert_points) == 2
        assert insert_points[0]["asDouble"] == 12
        assert insert_points[0]["timeUnixNano"] == str(NOW_NANOS)
        attributes = {kv["key"]: kv["value"]["stringValue"] for kv in insert_points[0]["attributes"]}
        assert attributes == {"topic": "clickhouse_logs", "partition": "3"}

        record_points = metrics[NEWEST_RECORD_AGE_METRIC]["gauge"]["dataPoints"]
        assert record_points[1]["asDouble"] == 900
        attributes = {kv["key"]: kv["value"]["stringValue"] for kv in record_points[1]["attributes"]}
        assert attributes == {"topic": "clickhouse_traces", "partition": "0"}

    @parameterized.expand(
        [
            ("url_only", "http://capture:4318/i/v1/metrics", ""),
            ("token_only", "", "phc_test"),
            ("neither", "", ""),
        ]
    )
    def test_task_is_noop_without_full_export_config(self, _name: str, url: str, token: str) -> None:
        with (
            override_settings(OTEL_METRICS_EXPORT_URL=url, OTEL_METRICS_EXPORT_TOKEN=token),
            patch(f"{TASK_MODULE}.sync_execute") as mock_execute,
            patch(f"{TASK_MODULE}.requests.post") as mock_post,
        ):
            logs_clickhouse_lag_metrics_task()

        mock_execute.assert_not_called()
        mock_post.assert_not_called()

    @override_settings(OTEL_METRICS_EXPORT_URL="http://capture:4318/i/v1/metrics", OTEL_METRICS_EXPORT_TOKEN="phc_test")
    def test_task_queries_both_lag_tables_and_posts_with_bearer_token(self) -> None:
        with (
            patch(f"{TASK_MODULE}.sync_execute") as mock_execute,
            patch(f"{TASK_MODULE}.requests.post") as mock_post,
        ):
            mock_execute.side_effect = [
                [("clickhouse_logs", 0, 5, 8)],
                [("clickhouse_traces", 1, 2, 3)],
            ]
            mock_post.return_value = MagicMock(status_code=200)

            logs_clickhouse_lag_metrics_task()

        assert mock_execute.call_count == 2
        queried_tables = [call.args[0] for call in mock_execute.call_args_list]
        assert any("logs_kafka_metrics" in q for q in queried_tables)
        assert any("trace_spans_kafka_metrics" in q for q in queried_tables)

        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert mock_post.call_args.args[0] == "http://capture:4318/i/v1/metrics"
        assert kwargs["headers"]["Authorization"] == "Bearer phc_test"
        body = kwargs["json"]
        names = {m["name"] for m in body["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]}
        assert names == {LAST_INSERT_AGE_METRIC, NEWEST_RECORD_AGE_METRIC}

    @override_settings(OTEL_METRICS_EXPORT_URL="http://capture:4318/i/v1/metrics", OTEL_METRICS_EXPORT_TOKEN="phc_test")
    def test_task_survives_one_table_failing_and_still_exports_the_other(self) -> None:
        with (
            patch(f"{TASK_MODULE}.sync_execute") as mock_execute,
            patch(f"{TASK_MODULE}.requests.post") as mock_post,
        ):
            mock_execute.side_effect = [
                Exception("table missing in this environment"),
                [("clickhouse_traces", 1, 2, 3)],
            ]
            mock_post.return_value = MagicMock(status_code=200)

            logs_clickhouse_lag_metrics_task()

        mock_post.assert_called_once()
        body = mock_post.call_args.kwargs["json"]
        points = body["resourceMetrics"][0]["scopeMetrics"][0]["metrics"][0]["gauge"]["dataPoints"]
        assert len(points) == 1
