import datetime as dt

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from parameterized import parameterized

from products.metrics.backend import gauge_writer
from products.metrics.backend.facade.contracts import GaugeSample

NOW = dt.datetime(2026, 10, 10, 12, tzinfo=dt.UTC)


def _sample(name: str, age: dt.timedelta, value: float = 1.0) -> GaugeSample:
    return GaugeSample(name=name, value=value, timestamp=NOW - age, labels={"insight_id": "7"})


class TestWriteGauges(SimpleTestCase):
    @parameterized.expand(
        [
            ("default_window", 0, None),
            ("backfill_window", 8, {"backfill_days": "8"}),
        ]
    )
    @patch("products.metrics.backend.gauge_writer.MAX_POINTS_PER_REQUEST", 2)
    @patch("products.metrics.backend.gauge_writer.internal_requests_session")
    def test_keeps_point_timestamps_drops_stale_points_and_sends_the_team_token(
        self,
        _name: str,
        backfill_days: int,
        expected_params: dict[str, str] | None,
        session: MagicMock,
    ) -> None:
        samples = [
            _sample("a", dt.timedelta(hours=1), 3.0),
            _sample("b", dt.timedelta(hours=2)),
            _sample("a", dt.timedelta(hours=3), 4.0),
            _sample("a", dt.timedelta(days=2), 5.0),
            _sample("a", dt.timedelta(days=9)),
        ]

        result = gauge_writer.write_gauges(
            samples,
            endpoint="http://capture/i/v1/metrics",
            token="phc_team",
            service_name="svc",
            now=NOW,
            backfill_days=backfill_days,
        )

        posts = session.return_value.post.call_args_list
        assert {post.kwargs["headers"]["authorization"] for post in posts} == {"Bearer phc_team"}
        assert [post.kwargs["params"] for post in posts] == [expected_params] * len(posts)
        points = []
        for post in posts:
            request = ExportMetricsServiceRequest.FromString(post.kwargs["data"])
            resource_metrics = request.resource_metrics[0]
            assert resource_metrics.resource.attributes[0].value.string_value == "svc"
            for metric in resource_metrics.scope_metrics[0].metrics:
                for point in metric.gauge.data_points:
                    timestamp = dt.datetime.fromtimestamp(point.time_unix_nano / 1e9, tz=dt.UTC)
                    points.append((metric.name, timestamp, point.as_double))
        expected = [
            ("a", NOW - dt.timedelta(hours=3), 4.0),
            ("a", NOW - dt.timedelta(hours=1), 3.0),
            ("b", NOW - dt.timedelta(hours=2), 1.0),
        ]
        if backfill_days:
            expected.insert(0, ("a", NOW - dt.timedelta(days=2), 5.0))
        assert sorted(points) == expected
        assert (result.written, result.dropped_stale) == (len(expected), len(samples) - len(expected))
