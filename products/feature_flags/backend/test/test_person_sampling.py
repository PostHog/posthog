from collections.abc import Callable
from typing import Optional

from django.test import SimpleTestCase

from parameterized import parameterized

from products.feature_flags.backend.person_sampling import (
    MIN_SAMPLED_MATCHES,
    SAMPLE_MODULUS,
    bounded_memory_settings,
    count_settings,
    sampled_or_exact_count,
)


class TestPersonSamplingSettings(SimpleTestCase):
    @parameterized.expand(
        [
            ("memory bounded", bounded_memory_settings),
            ("sampled count", lambda: count_settings(64)),
            ("exact count", lambda: count_settings(None)),
        ]
    )
    def test_settings_reject_a_partial_result_on_timeout(self, _name, build_settings):
        # Left unset, the mode inherits the cluster profile, which may return whatever the
        # query aggregated before the timeout. The sampled count would then multiply that
        # partial tally by the modulus and report it as an audience size.
        assert build_settings().timeout_overflow_mode == "throw"


class TestSampledOrExactCount(SimpleTestCase):
    # Distinct from every extrapolation below, so the returned value names the branch that ran.
    EXACT_COUNT = 7

    def _stub_count(self, sampled: int) -> tuple[Callable[[Optional[int]], int], list[Optional[int]]]:
        moduli: list[Optional[int]] = []

        def run_count(sample_modulus: Optional[int]) -> int:
            moduli.append(sample_modulus)
            return sampled if sample_modulus is not None else self.EXACT_COUNT

        return run_count, moduli

    @parameterized.expand(
        [
            ("above the threshold", MIN_SAMPLED_MATCHES + 1),
            # The boundary itself: `>` in place of `>=` reruns exact here and fails.
            ("at the threshold", MIN_SAMPLED_MATCHES),
        ]
    )
    def test_a_large_enough_sample_is_extrapolated_without_an_exact_rerun(self, _name, sampled):
        run_count, moduli = self._stub_count(sampled)

        # Returning the sample unmultiplied would under-report the audience by the modulus.
        assert sampled_or_exact_count(run_count) == sampled * SAMPLE_MODULUS
        assert moduli == [SAMPLE_MODULUS]

    def test_a_small_sample_is_discarded_for_an_exact_count(self):
        run_count, moduli = self._stub_count(MIN_SAMPLED_MATCHES - 1)

        assert sampled_or_exact_count(run_count) == self.EXACT_COUNT
        # The probe still runs and is paid for before the exact count replaces it.
        assert moduli == [SAMPLE_MODULUS, None]
