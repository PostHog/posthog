from collections.abc import Callable

from django.test import SimpleTestCase

from parameterized import parameterized
from prometheus_client import REGISTRY

from products.replay_vision.backend.temporal.metrics import (
    record_activity_duration,
    record_credits_consumed,
    record_failure_kind,
    record_gemini_cleanup_backlog,
    record_ineligible_kind,
    record_observation,
    record_observation_e2e,
    record_provider_call,
    record_quota_exhausted_skip,
    record_side_effect_failure,
    record_sweep_outcome,
)


def _sample(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


class TestRecordHelpers(SimpleTestCase):
    # Each helper runs inside activity bodies and error handlers, where a prom label
    # mismatch would raise at runtime; one call per helper locks the label sets in.
    @parameterized.expand(
        [
            (
                "observation",
                lambda: record_observation("succeeded", "monitor"),
                "replay_vision_observations_total",
                {"status": "succeeded", "scanner_type": "monitor"},
                1.0,
            ),
            (
                "failure_kind",
                lambda: record_failure_kind("provider_transient", "monitor"),
                "replay_vision_failure_kinds_total",
                {"kind": "provider_transient", "scanner_type": "monitor"},
                1.0,
            ),
            (
                "ineligible_kind",
                lambda: record_ineligible_kind("too_short"),
                "replay_vision_ineligible_kinds_total",
                {"kind": "too_short"},
                1.0,
            ),
            (
                "activity_duration",
                lambda: record_activity_duration("some_activity", "failed", 1.5),
                "replay_vision_activity_duration_seconds_count",
                {"activity": "some_activity", "status": "failed"},
                1.0,
            ),
            (
                "provider_call",
                lambda: record_provider_call("gemini", "gemini-3-flash", "monitor", "ok", 2.0),
                "replay_vision_provider_call_seconds_count",
                {"provider": "gemini", "model": "gemini-3-flash", "scanner_type": "monitor", "outcome": "ok"},
                1.0,
            ),
            (
                "quota_exhausted_skip",
                lambda: record_quota_exhausted_skip("monitor"),
                "replay_vision_quota_exhausted_skips_total",
                {"scanner_type": "monitor"},
                1.0,
            ),
            (
                "credits_consumed",
                lambda: record_credits_consumed("monitor", "gemini-3-flash", 5),
                "replay_vision_credits_consumed_total",
                {"scanner_type": "monitor", "model": "gemini-3-flash"},
                5.0,
            ),
            (
                "sweep_outcome",
                lambda: record_sweep_outcome("throttled"),
                "replay_vision_sweep_outcomes_total",
                {"outcome": "throttled"},
                1.0,
            ),
            (
                "sweep_candidates",
                lambda: record_sweep_outcome("candidates_found", candidates=3),
                "replay_vision_sweep_candidates_total",
                {},
                3.0,
            ),
            (
                "observation_e2e",
                lambda: record_observation_e2e("monitor", 120.0),
                "replay_vision_observation_e2e_seconds_count",
                {"scanner_type": "monitor"},
                1.0,
            ),
            (
                "side_effect_failure",
                lambda: record_side_effect_failure("signal"),
                "replay_vision_side_effect_failures_total",
                {"effect": "signal"},
                1.0,
            ),
        ]
    )
    def test_record_helper_increments_prom_sample(
        self,
        _name: str,
        record: Callable[[], None],
        sample_name: str,
        labels: dict[str, str],
        expected_delta: float,
    ) -> None:
        before = _sample(sample_name, labels)
        record()
        assert _sample(sample_name, labels) == before + expected_delta

    def test_gemini_cleanup_backlog_is_a_gauge(self) -> None:
        record_gemini_cleanup_backlog(7)
        assert _sample("replay_vision_gemini_cleanup_backlog", {}) == 7.0
        record_gemini_cleanup_backlog(2)
        assert _sample("replay_vision_gemini_cleanup_backlog", {}) == 2.0
