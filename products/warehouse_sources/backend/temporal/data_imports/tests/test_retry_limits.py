import datetime as dt

from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.retry_limits import (
    FAILING_SCHEMA_MAX_IMPORT_ATTEMPTS,
    FAILING_SCHEMA_RUN_GAP_BASE,
    FAILING_SCHEMA_RUN_GAP_CAP,
    GIVE_UP_AFTER_FAILED_RUNS,
    import_retry_budget,
    min_gap_between_runs,
)


class TestImportRetryBudget(SimpleTestCase):
    @parameterized.expand(
        [
            ("healthy_keeps_resumable_cap", 20, 0, 20),
            ("one_failure_keeps_cap", 20, 1, 20),
            ("last_run_before_the_threshold_keeps_cap", 20, GIVE_UP_AFTER_FAILED_RUNS - 1, 20),
            ("threshold_cuts_resumable_cap", 20, GIVE_UP_AFTER_FAILED_RUNS, FAILING_SCHEMA_MAX_IMPORT_ATTEMPTS),
            ("past_threshold_cuts_incremental_cap", 9, 12, FAILING_SCHEMA_MAX_IMPORT_ATTEMPTS),
            ("never_raises_a_smaller_cap", 1, 50, 1),
        ]
    )
    def test_budget(self, _name: str, budget: int, failed_runs: int, expected: int) -> None:
        assert import_retry_budget(budget, failed_runs) == expected


class TestMinGapBetweenRuns(SimpleTestCase):
    @parameterized.expand(
        [
            ("healthy_schema_has_no_gap", 0, None),
            ("below_threshold_has_no_gap", GIVE_UP_AFTER_FAILED_RUNS - 1, None),
            ("threshold_starts_at_the_base", GIVE_UP_AFTER_FAILED_RUNS, FAILING_SCHEMA_RUN_GAP_BASE),
            ("gap_doubles_per_failed_run", GIVE_UP_AFTER_FAILED_RUNS + 1, FAILING_SCHEMA_RUN_GAP_BASE * 2),
            ("gap_stops_at_the_cap", GIVE_UP_AFTER_FAILED_RUNS + 20, FAILING_SCHEMA_RUN_GAP_CAP),
            # A schema that has failed for months must not build a timedelta that overflows.
            ("an_absurd_streak_stays_at_the_cap", 10**9, FAILING_SCHEMA_RUN_GAP_CAP),
        ]
    )
    def test_gap(self, _name: str, failed_runs: int, expected: dt.timedelta | None) -> None:
        assert min_gap_between_runs(failed_runs) == expected

    def test_the_gap_never_passes_the_cap(self) -> None:
        for failed_runs in range(GIVE_UP_AFTER_FAILED_RUNS, GIVE_UP_AFTER_FAILED_RUNS + 40):
            gap = min_gap_between_runs(failed_runs)
            assert gap is not None
            assert gap <= FAILING_SCHEMA_RUN_GAP_CAP
