from unittest import TestCase

from parameterized import parameterized

from products.experiments.backend.flag_cleanup import cleanup_plan


def _variants(*pairs: tuple[str, int]) -> list[dict]:
    return [{"key": key, "rollout_percentage": pct} for key, pct in pairs]


class TestCleanupPlan(TestCase):
    @parameterized.expand(
        [
            # (name, conclusion, variants, keep, remove, confident)
            ("won_shipped", "won", _variants(("control", 0), ("test", 100)), "test", {"control"}, True),
            # A shipped variant (at 100%) wins even among several — precedence over the ambiguity branch below.
            (
                "won_shipped_among_many",
                "won",
                _variants(("control", 0), ("red", 0), ("blue", 100)),
                "blue",
                {"control", "red"},
                True,
            ),
            # Won but nothing shipped: single non-control is a best guess, flagged low-confidence.
            ("won_unshipped_single", "won", _variants(("control", 50), ("test", 50)), "test", {"control"}, False),
            # Won but nothing shipped and multiple non-control: don't guess — keep nothing, low-confidence.
            (
                "won_unshipped_ambiguous",
                "won",
                _variants(("control", 34), ("red", 33), ("blue", 33)),
                None,
                {"control", "red", "blue"},
                False,
            ),
            ("lost", "lost", _variants(("control", 50), ("test", 50)), "control", {"test"}, True),
            ("invalid", "invalid", _variants(("control", 50), ("test", 50)), "control", {"test"}, True),
            ("inconclusive", "inconclusive", _variants(("control", 50), ("test", 50)), "control", {"test"}, False),
            ("stopped_early", "stopped_early", _variants(("control", 50), ("test", 50)), "control", {"test"}, False),
            # No variant named "control": baseline falls back to the first variant.
            (
                "no_control_fallback",
                "lost",
                _variants(("baseline", 50), ("variant", 50)),
                "baseline",
                {"variant"},
                True,
            ),
        ]
    )
    def test_cleanup_plan(self, _name, conclusion, variants, keep, remove, confident):
        plan = cleanup_plan(conclusion, variants)

        self.assertEqual(plan.keep_variant, keep)
        self.assertEqual(set(plan.remove_variants), remove)
        self.assertEqual(plan.confident, confident)
