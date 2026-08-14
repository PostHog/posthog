from django.test import SimpleTestCase

from parameterized import parameterized

from products.replay_vision.backend.observation_window import (
    COVERAGE_TIERS,
    estimate_summary_cost_usd,
    estimate_summary_credits,
    synthesis_llm_calls,
)


class TestSummaryCostEstimates(SimpleTestCase):
    @parameterized.expand(
        [
            ("empty", 0, 0),
            ("single", 1, 1),
            ("at_chunk_size", 100, 1),
            ("just_over_chunk_size", 101, 3),
            ("two_full_chunks", 200, 3),
            ("run_ceiling", 2000, 21),
        ]
    )
    def test_llm_call_count(self, _label: str, observation_count: int, expected_calls: int) -> None:
        # The preview's cost math hangs off this count; an off-by-one at the chunk boundary would
        # misquote every estimate and disagree with what the run actually bills.
        self.assertEqual(synthesis_llm_calls(observation_count), expected_calls)

    def test_estimate_grows_with_coverage_and_stays_in_a_sane_range(self) -> None:
        # A per-token vs per-megatoken slip (or swapped input/output rates) makes the estimate off by
        # orders of magnitude — the range assertions catch that; monotonicity catches a tier whose
        # deeper coverage would absurdly quote cheaper.
        self.assertEqual(estimate_summary_cost_usd(0), 0.0)
        costs = [estimate_summary_cost_usd(tier.max_observations) for tier in COVERAGE_TIERS]
        self.assertEqual(costs, sorted(costs))
        self.assertGreater(costs[0], 0)
        self.assertLess(costs[0], 0.05)  # standard: a single pass costs around a cent
        self.assertLess(costs[-1], 1.0)  # complete: the full 2,000-observation map-reduce stays under a dollar

    def test_credit_estimate_is_whole_and_never_free_for_a_nonzero_run(self) -> None:
        # The UI quotes whole credits; rounding a sub-cent single pass down to 0 would advertise a
        # billable run as free.
        self.assertEqual(estimate_summary_credits(0), 0)
        self.assertEqual(estimate_summary_credits(1), 1)
        credits = [estimate_summary_credits(tier.max_observations) for tier in COVERAGE_TIERS]
        self.assertEqual(credits, sorted(credits))
        self.assertGreaterEqual(credits[0], 1)
        self.assertLess(credits[-1], 100)  # complete stays under a dollar
