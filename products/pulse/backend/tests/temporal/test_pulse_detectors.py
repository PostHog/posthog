import asyncio

import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import PulseScanConfig

from products.pulse.backend.temporal.detection import _evaluate_one, score_series
from products.pulse.backend.temporal.detectors import DetectionResult, PulseDetector, get_detector, register_detector
from products.pulse.backend.temporal.types import CandidateMetric, EnrichedFinding, Finding, MetricDescriptor

DETECTION = "products.pulse.backend.temporal.detection"


class TestDetectorRegistry:
    def test_get_detector_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="Unknown detection mode: nope"):
            get_detector("nope")

    def test_get_detector_returns_change_v1(self):
        detector = get_detector("change_v1")
        assert isinstance(detector, PulseDetector)

    def test_register_detector_adds_to_registry(self):
        @register_detector("test_only_mode")
        class _Dummy(PulseDetector):
            def detect(self, current, baseline, min_change_pct, robust_z_threshold, min_baseline_value):
                return DetectionResult(
                    triggered=False,
                    baseline_median=0.0,
                    change_pct=0.0,
                    impact=0.0,
                    robust_z=0.0,
                )

        assert isinstance(get_detector("test_only_mode"), _Dummy)

    def test_detection_result_fields(self):
        result = DetectionResult(
            triggered=True,
            baseline_median=100.0,
            change_pct=-0.5,
            impact=5.0,
            robust_z=3.2,
        )
        assert result.triggered is True
        assert result.baseline_median == 100.0
        assert result.impact == 5.0
        assert result.robust_z == 3.2


class TestNoStaleZScoreReferences:
    def test_finding_has_no_z_score_field(self):
        assert "z_score" not in Finding.model_fields
        assert "robust_z" in Finding.model_fields
        assert "impact" in Finding.model_fields
        assert "z_score" not in EnrichedFinding.model_fields
        assert "robust_z" in EnrichedFinding.model_fields
        assert "impact" in EnrichedFinding.model_fields


class TestChangeV1Gating:
    def _detect(self, current, baseline, min_change_pct=0.25, robust_z_threshold=3.0, min_baseline_value=0.0):
        return get_detector("change_v1").detect(
            current, baseline, min_change_pct, robust_z_threshold, min_baseline_value
        )

    @pytest.mark.parametrize(
        "name,current,baseline,kwargs,expected_triggered",
        [
            ("large_change_triggers", 200.0, [100.0, 101.0, 99.0, 100.0], {}, True),
            ("below_min_change_does_not", 105.0, [100.0, 101.0, 99.0, 100.0], {"min_change_pct": 0.25}, False),
            # A change against a zero-variance baseline (MAD=0 → robust_z=0) is the clearest signal and must
            # still fire — robust_z is deliberately not a gate.
            ("flat_baseline_still_triggers", 50.0, [100.0, 100.0, 100.0, 100.0], {}, True),
            ("below_volume_floor_does_not", 5.0, [1.0, 1.0, 1.0, 1.0], {"min_baseline_value": 100.0}, False),
        ],
    )
    def test_gating(self, name, current, baseline, kwargs, expected_triggered):
        result = self._detect(current, baseline, **kwargs)
        assert result.triggered is expected_triggered

    def test_flat_baseline_robust_z_is_zero_but_not_a_gate(self):
        result = self._detect(50.0, [100.0, 100.0, 100.0, 100.0])
        assert result.robust_z == 0.0
        assert result.triggered is True


class TestDetectionFailureMetric:
    @pytest.mark.asyncio
    async def test_evaluate_one_counts_candidate_failures(self):
        # A candidate whose query raises must be counted, so an all-errored scan is distinguishable
        # from a quiet one (both yield zero findings).
        candidate = CandidateMetric(descriptor=MetricDescriptor(source="top_event", label="Boom", query={}))
        config = PulseScanConfig(baseline_weeks=4, min_change_pct=0.25, robust_z_threshold=3.0, min_baseline_value=0.0)
        with (
            patch(f"{DETECTION}.run_trends_query_sync", side_effect=RuntimeError("query boom")),
            patch(f"{DETECTION}.increment_detection_outcome") as mock_counter,
        ):
            result = await _evaluate_one(MagicMock(id=1), candidate, config, asyncio.Semaphore(1))
        assert result is None
        mock_counter.assert_called_once_with("failed")


class TestScoreSeries:
    def test_scores_without_gating(self):
        # A change BELOW min_change_pct: _evaluate_candidate would drop it (gate),
        # but score_series must still return the computed numbers (no gate).
        config = PulseScanConfig(baseline_weeks=4, min_change_pct=0.25, robust_z_threshold=3.0, min_baseline_value=0.0)
        # 4 baseline weeks ~100, current 105 (+5%, below the 25% gate), + a trailing partial week
        scored = score_series([100.0, 101.0, 99.0, 100.0, 105.0, 0.0], config)
        assert scored is not None
        result, current, series = scored
        assert current == 105.0
        assert result.triggered is False  # below gate, but still returned
        assert round(result.change_pct, 3) == 0.05
        assert len(series) == config.baseline_weeks + 1

    def test_returns_none_on_insufficient_data(self):
        config = PulseScanConfig(baseline_weeks=4, min_change_pct=0.25, robust_z_threshold=3.0, min_baseline_value=0.0)
        assert score_series([1.0, 2.0], config) is None
