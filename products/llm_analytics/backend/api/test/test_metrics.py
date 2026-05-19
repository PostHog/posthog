from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.llm_analytics.backend.api.metrics import LLMA_REQUEST_LATENCY_BUCKETS, llma_track_latency


class TestLLMAnalyticsMetrics(SimpleTestCase):
    @parameterized.expand([("single", LLMA_REQUEST_LATENCY_BUCKETS, 30)])
    def test_request_latency_buckets_are_monotonic(self, _: str, buckets: list[float], expected_count: int):
        assert len(buckets) == expected_count
        assert buckets == sorted(buckets)
        assert buckets[-1] == 300.0

    @patch("products.llm_analytics.backend.api.metrics.LLMA_REQUEST_LATENCY")
    @patch("products.llm_analytics.backend.api.metrics.time.perf_counter")
    def test_track_latency_observes_histogram(self, mock_perf_counter, mock_histogram):
        mock_perf_counter.side_effect = [10.0, 10.2]
        observer = MagicMock()
        mock_histogram.labels.return_value = observer

        @llma_track_latency("llma_test_endpoint")
        def operation():
            return "ok"

        assert operation() == "ok"
        mock_histogram.labels.assert_called_once_with(endpoint="llma_test_endpoint")
        observer.observe.assert_called_once()
        self.assertAlmostEqual(observer.observe.call_args.args[0], 0.2)

    @patch("products.llm_analytics.backend.api.metrics.LLMA_REQUEST_LATENCY")
    @patch("products.llm_analytics.backend.api.metrics.time.perf_counter")
    def test_track_latency_observes_on_exception(self, mock_perf_counter, mock_histogram):
        mock_perf_counter.side_effect = [10.0, 10.5]
        observer = MagicMock()
        mock_histogram.labels.return_value = observer

        @llma_track_latency("llma_test_endpoint")
        def failing_operation():
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            failing_operation()

        observer.observe.assert_called_once()
        self.assertAlmostEqual(observer.observe.call_args.args[0], 0.5)
