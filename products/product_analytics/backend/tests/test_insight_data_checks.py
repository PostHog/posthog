from django.test import SimpleTestCase

from parameterized import parameterized

from products.product_analytics.backend.facade.enums import InsightDataCheckKey, InsightDataCheckLevel
from products.product_analytics.backend.insight_data_checks import DataCheckCounts, evaluate_data_checks

PASSED = InsightDataCheckLevel.PASSED
WARNING = InsightDataCheckLevel.WARNING
PROBLEM = InsightDataCheckLevel.PROBLEM


def counts(
    events: int,
    *,
    local: int = 0,
    bots: int = 0,
    duplicates: int = 0,
    sample_rate: float = 1.0,
) -> DataCheckCounts:
    return DataCheckCounts(
        events=events,
        local_events=local,
        bot_events=bots,
        distinct_events=events - duplicates,
        sample_rate=sample_rate,
    )


class TestEvaluateDataChecks(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "local_tiny_share_still_counts",
                InsightDataCheckKey.LOCAL_DEVELOPMENT,
                counts(1000000, local=60),
                WARNING,
            ),
            ("local_under_50_events", InsightDataCheckKey.LOCAL_DEVELOPMENT, counts(100, local=49), PASSED),
            ("local_fifth_is_a_problem", InsightDataCheckKey.LOCAL_DEVELOPMENT, counts(1000, local=200), PROBLEM),
            ("bots_small_share_is_a_warning", InsightDataCheckKey.BOT_TRAFFIC, counts(10000, bots=200), WARNING),
            ("bots_under_one_percent", InsightDataCheckKey.BOT_TRAFFIC, counts(100000, bots=500), PASSED),
            ("duplicates_under_100_events", InsightDataCheckKey.DUPLICATE_EVENTS, counts(1000, duplicates=99), PASSED),
            (
                "duplicates_under_five_percent",
                InsightDataCheckKey.DUPLICATE_EVENTS,
                counts(10000, duplicates=400),
                PASSED,
            ),
            (
                "duplicates_over_both_floors",
                InsightDataCheckKey.DUPLICATE_EVENTS,
                counts(10000, duplicates=600),
                WARNING,
            ),
            (
                "duplicates_fifth_is_a_problem",
                InsightDataCheckKey.DUPLICATE_EVENTS,
                counts(1000, duplicates=250),
                PROBLEM,
            ),
        ]
    )
    def test_level_follows_count_and_share(
        self, _name: str, key: InsightDataCheckKey, check_counts: DataCheckCounts, expected: InsightDataCheckLevel
    ) -> None:
        checks = evaluate_data_checks(check_counts)
        levels = {check.key: check.level for check in checks}
        assert levels[key] == expected
        assert all(level == PASSED for other, level in levels.items() if other != key)

    @parameterized.expand(
        [
            ("every_event_read", 1.0, "66 of these events came from local development"),
            ("sample_read", 0.01, "About 6,600 of these events came from local development"),
        ]
    )
    def test_a_count_from_a_sample_is_scaled_up_to_the_whole_insight(
        self, _name: str, sample_rate: float, expected: str
    ) -> None:
        checks = evaluate_data_checks(counts(1000000, local=66, sample_rate=sample_rate))
        check = next(check for check in checks if check.key == InsightDataCheckKey.LOCAL_DEVELOPMENT)
        assert check.result == expected
