from unittest.mock import MagicMock, patch

from products.signals.backend.temporal import metrics


def _mock_meter() -> MagicMock:
    meter = MagicMock()
    meter.create_counter.return_value = MagicMock()
    return meter


class TestCounterHelpers:
    def test_funnel_records_when_in_context(self):
        meter = _mock_meter()
        with (
            patch.object(metrics, "_in_temporal_context", return_value=True),
            patch.object(metrics, "get_metric_meter", return_value=meter) as get_meter,
        ):
            metrics.increment_funnel(metrics.FUNNEL_STAGE_GROUPED, "error_tracking")

        assert get_meter.call_args[0][0] == {"stage": "grouped", "source_product": "error_tracking"}
        meter.create_counter.assert_called_once()
        meter.create_counter.return_value.add.assert_called_once_with(1)

    def test_funnel_defaults_source_product(self):
        meter = _mock_meter()
        with (
            patch.object(metrics, "_in_temporal_context", return_value=True),
            patch.object(metrics, "get_metric_meter", return_value=meter) as get_meter,
        ):
            metrics.increment_funnel(metrics.FUNNEL_STAGE_EMITTED)

        assert get_meter.call_args[0][0] == {"stage": "emitted", "source_product": "unknown"}

    def test_helpers_noop_outside_temporal_context(self):
        with (
            patch.object(metrics, "_in_temporal_context", return_value=False),
            patch.object(metrics, "get_metric_meter") as get_meter,
        ):
            metrics.increment_funnel(metrics.FUNNEL_STAGE_GROUPED, "error_tracking")
            metrics.increment_dropped("grouping_parallel", "ValueError")
            metrics.increment_report_completed("ready")
            metrics.increment_llm_call("match", metrics.LLM_STATUS_OK)
            metrics.increment_ch_wait_timeout()
            metrics.increment_scout_run("completed")

        get_meter.assert_not_called()

    def test_zero_count_is_a_noop(self):
        with (
            patch.object(metrics, "_in_temporal_context", return_value=True),
            patch.object(metrics, "get_metric_meter") as get_meter,
        ):
            metrics.increment_funnel(metrics.FUNNEL_STAGE_GROUPED, count=0)
            metrics.increment_dropped("grouping_parallel", "ValueError", count=0)

        get_meter.assert_not_called()

    def test_report_completed_label(self):
        meter = _mock_meter()
        with (
            patch.object(metrics, "_in_temporal_context", return_value=True),
            patch.object(metrics, "get_metric_meter", return_value=meter) as get_meter,
        ):
            metrics.increment_report_completed("not_actionable")

        assert get_meter.call_args[0][0] == {"result": "not_actionable"}

    def test_dropped_labels(self):
        meter = _mock_meter()
        with (
            patch.object(metrics, "_in_temporal_context", return_value=True),
            patch.object(metrics, "get_metric_meter", return_value=meter) as get_meter,
        ):
            metrics.increment_dropped("grouping_parallel", "ValueError")

        assert get_meter.call_args[0][0] == {"stage": "grouping_parallel", "reason": "ValueError"}

    def test_llm_call_labels(self):
        meter = _mock_meter()
        with (
            patch.object(metrics, "_in_temporal_context", return_value=True),
            patch.object(metrics, "get_metric_meter", return_value=meter) as get_meter,
        ):
            metrics.increment_llm_call("match", metrics.LLM_STATUS_ERROR)

        assert get_meter.call_args[0][0] == {"stage": "match", "status": "error"}

    def test_ch_wait_timeout_counter(self):
        meter = _mock_meter()
        with (
            patch.object(metrics, "_in_temporal_context", return_value=True),
            patch.object(metrics, "get_metric_meter", return_value=meter),
        ):
            metrics.increment_ch_wait_timeout()

        meter.create_counter.assert_called_once()
        meter.create_counter.return_value.add.assert_called_once_with(1)
