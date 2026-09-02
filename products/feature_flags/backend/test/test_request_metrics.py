from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.constants import FlagRequestType

from products.feature_flags.backend.request_metrics import UNATTRIBUTED_LIBRARY, _rows_for_hour, record_request_metrics

# 2022-05-07 12:00:00 UTC and the hour after it.
HOUR_ONE = 1651924800
HOUR_TWO = 1651928400


class TestFlagRequestMetrics(SimpleTestCase):
    @parameterized.expand(
        [
            ("remainder is recorded", 10, {"posthog-js": 6}, [("posthog-js", 6), (UNATTRIBUTED_LIBRARY, 4)]),
            ("no remainder", 10, {"posthog-js": 10}, [("posthog-js", 10)]),
            ("libraries ahead of the total", 10, {"posthog-js": 12}, [("posthog-js", 12)]),
            ("no libraries", 10, {}, [(UNATTRIBUTED_LIBRARY, 10)]),
            ("empty library dropped", 10, {"posthog-js": 0, "posthog-node": 10}, [("posthog-node", 10)]),
        ]
    )
    def test_rows_for_hour(self, _name: str, total: int, library_counts: dict[str, int], expected) -> None:
        self.assertEqual(_rows_for_hour(total, library_counts), expected)

    @override_settings(FLAG_REQUEST_METRICS_ENABLED=True)
    def test_counts_are_grouped_into_the_hour_they_happened_in(self) -> None:
        producer = MagicMock()

        with patch("products.feature_flags.backend.request_metrics.get_producer", return_value=producer):
            record_request_metrics(
                team_id=7,
                request_type=FlagRequestType.DECIDE,
                total_counts_by_time={HOUR_ONE: 3, HOUR_ONE + 120: 4, HOUR_TWO: 5},
                library_counts_by_time={"posthog-js": {HOUR_ONE: 3, HOUR_ONE + 120: 4, HOUR_TWO: 5}},
            )

        rows = [call.kwargs["data"] for call in producer.produce.call_args_list]
        self.assertEqual(
            [(row["timestamp"], row["metric_kind"], row["metric_name"], row["count"]) for row in rows],
            [
                ("2022-05-07 12:00:00.000000", "decide", "posthog-js", 7),
                ("2022-05-07 13:00:00.000000", "decide", "posthog-js", 5),
            ],
        )

    @override_settings(FLAG_REQUEST_METRICS_ENABLED=True)
    def test_requests_with_no_library_are_recorded_as_unattributed(self) -> None:
        producer = MagicMock()

        with patch("products.feature_flags.backend.request_metrics.get_producer", return_value=producer):
            record_request_metrics(
                team_id=7,
                request_type=FlagRequestType.LOCAL_EVALUATION,
                total_counts_by_time={HOUR_ONE: 10},
                library_counts_by_time={"posthog-python": {HOUR_ONE: 4}},
            )

        rows = [call.kwargs["data"] for call in producer.produce.call_args_list]
        self.assertEqual(
            [(row["metric_name"], row["count"]) for row in rows],
            [("posthog-python", 4), (UNATTRIBUTED_LIBRARY, 6)],
        )

    @override_settings(FLAG_REQUEST_METRICS_ENABLED=False)
    def test_nothing_is_recorded_when_the_kill_switch_is_off(self) -> None:
        with patch("products.feature_flags.backend.request_metrics.get_producer") as get_producer:
            record_request_metrics(
                team_id=7,
                request_type=FlagRequestType.DECIDE,
                total_counts_by_time={HOUR_ONE: 5},
                library_counts_by_time={},
            )

        get_producer.assert_not_called()
