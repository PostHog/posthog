from unittest.mock import MagicMock, patch

from products.signals.backend.temporal import metrics
from products.signals.backend.temporal.metrics import (
    SIGNALS_ACTIVITY_TYPES,
    SIGNALS_WORKFLOW_TYPES,
    SignalsMetricsInterceptor,
)


def _mock_meter() -> MagicMock:
    meter = MagicMock()
    meter.create_counter.return_value = MagicMock()
    meter.create_histogram_timedelta.return_value = MagicMock()
    return meter


class TestCounterHelpers:
    def test_funnel_stage_records_when_in_context(self):
        meter = _mock_meter()
        with (
            patch.object(metrics, "_in_temporal_context", return_value=True),
            patch.object(metrics, "get_metric_meter", return_value=meter) as get_meter,
        ):
            metrics.increment_funnel_stage(metrics.FUNNEL_STAGE_GROUPED, "error_tracking")

        assert get_meter.call_args[0][0] == {"stage": "grouped", "source_product": "error_tracking"}
        meter.create_counter.assert_called_once()
        meter.create_counter.return_value.add.assert_called_once_with(1)

    def test_helpers_noop_outside_temporal_context(self):
        with (
            patch.object(metrics, "_in_temporal_context", return_value=False),
            patch.object(metrics, "get_metric_meter") as get_meter,
        ):
            metrics.increment_funnel_stage(metrics.FUNNEL_STAGE_GROUPED, "error_tracking")
            metrics.increment_signal_dropped("safety_filter", "prompt_injection")
            metrics.increment_report_outcome("ready")
            metrics.increment_agentic_research("actionable")
            metrics.increment_llm_retry("match")

        get_meter.assert_not_called()

    def test_report_outcome_label(self):
        meter = _mock_meter()
        with (
            patch.object(metrics, "_in_temporal_context", return_value=True),
            patch.object(metrics, "get_metric_meter", return_value=meter) as get_meter,
        ):
            metrics.increment_report_outcome("not_actionable")

        assert get_meter.call_args[0][0] == {"outcome": "not_actionable"}

    def test_llm_tokens_recorded_from_usage(self):
        meter = _mock_meter()
        response = MagicMock()
        response.usage.input_tokens = 120
        response.usage.output_tokens = 35
        with (
            patch.object(metrics, "_in_temporal_context", return_value=True),
            patch.object(metrics, "get_metric_meter", return_value=meter),
        ):
            metrics.record_llm_tokens(stage="match", model="claude-sonnet-4-5", response=response)

        added = [c.args[0] for c in meter.create_counter.return_value.add.call_args_list]
        assert added == [120, 35]

    def test_ch_wait_timeout_emits_counter(self):
        meter = _mock_meter()
        with (
            patch.object(metrics, "_in_temporal_context", return_value=True),
            patch.object(metrics, "get_metric_meter", return_value=meter),
        ):
            metrics.record_ch_wait(started_at=0.0, timed_out=True)

        # One histogram (latency) + one counter (timeout)
        meter.create_histogram_timedelta.assert_called_once()
        meter.create_counter.assert_called_once()

    def test_ch_wait_success_skips_timeout_counter(self):
        meter = _mock_meter()
        with (
            patch.object(metrics, "_in_temporal_context", return_value=True),
            patch.object(metrics, "get_metric_meter", return_value=meter),
        ):
            metrics.record_ch_wait(started_at=0.0, timed_out=False)

        meter.create_histogram_timedelta.assert_called_once()
        meter.create_counter.assert_not_called()


class TestInterceptor:
    def test_builds_activity_and_workflow_interceptors(self):
        interceptor = SignalsMetricsInterceptor()
        assert interceptor.intercept_activity(MagicMock()) is not None
        assert interceptor.workflow_interceptor_class(MagicMock()) is not None


class TestTypeSets:
    def test_activity_types_have_no_stale_entries(self):
        """Every name in SIGNALS_ACTIVITY_TYPES must map to a registered signals activity.

        Guards against typos and against an activity being renamed/removed without
        updating the interceptor's allowlist.
        """
        from products.signals.backend.temporal import ACTIVITIES

        registered = {fn.__name__ for fn in ACTIVITIES}
        stale = SIGNALS_ACTIVITY_TYPES - registered
        assert stale == set(), f"SIGNALS_ACTIVITY_TYPES references unregistered activities: {stale}"

    def test_core_pipeline_activities_are_covered(self):
        core = {
            "safety_filter_activity",
            "flush_signals_to_s3_activity",
            "read_signals_from_s3_activity",
            "get_embedding_activity",
            "generate_search_queries_activity",
            "run_signal_semantic_search_activity",
            "match_signal_to_report_activity",
            "assign_and_emit_signal_activity",
            "wait_for_signal_in_clickhouse_activity",
            "report_safety_judge_activity",
            "select_repository_activity",
            "run_agentic_report_activity",
        }
        assert core <= SIGNALS_ACTIVITY_TYPES

    def test_workflow_types_are_bounded_lifecycle_workflows(self):
        assert SIGNALS_WORKFLOW_TYPES == {"signal-emitter", "signal-report-summary"}
