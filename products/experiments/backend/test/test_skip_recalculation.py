from datetime import UTC, datetime

from django.test import SimpleTestCase

from parameterized import parameterized

from products.experiments.backend.metric_calculation.skip_recalculation import (
    MetricHistory,
    MetricKey,
    MetricRunOutcome,
    MetricSkip,
    SkipCheck,
    find_metric_skips,
)
from products.experiments.backend.metric_calculation.skip_recalculation_checks import (
    SKIP_REASON_UNCHANGED_VALIDATION_ERROR,
    skip_unchanged_validation_error,
)

_KEY = "key-now"
_FAILED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def _outcome(error_type: str | None, calculation_key: str | None = _KEY, run: str = "run-1") -> MetricRunOutcome:
    return MetricRunOutcome(
        recalculation_id=run,
        error_type=error_type,
        calculation_key=calculation_key,
        failed_at=_FAILED_AT if error_type else None,
    )


def _history(*outcomes: MetricRunOutcome) -> MetricHistory:
    return MetricHistory(
        key=MetricKey(experiment_id=1, metric_uuid="m1"),
        calculation_key=_KEY,
        outcomes=outcomes,
    )


def _skip(reason: str) -> MetricSkip:
    return MetricSkip(
        reason=reason, skipped_error_type="validation_error", failed_recalculation_id="run-1", failed_at=None
    )


def _always(reason: str) -> SkipCheck:
    return lambda history: _skip(reason)


def _never(history: MetricHistory) -> MetricSkip | None:
    return None


def _raises(history: MetricHistory) -> MetricSkip | None:
    raise RuntimeError("check bug")


class TestSkipRecalculation(SimpleTestCase):
    @parameterized.expand(
        [
            ("first_skip_wins", [_never, _always("a"), _always("b")], "a"),
            ("raising_check_fails_open", [_raises, _always("b")], "b"),
            ("only_raising_check_runs_the_metric", [_raises], None),
            ("no_check_skips", [_never], None),
        ]
    )
    def test_find_metric_skips(self, name: str, checks: list[SkipCheck], expected_reason: str | None) -> None:
        skips = find_metric_skips([_history()], checks)

        key = MetricKey(experiment_id=1, metric_uuid="m1")
        assert (skips[key].reason if key in skips else None) == expected_reason

    @parameterized.expand(
        [
            ("same_key", (_outcome("validation_error"),), True),
            ("changed_key", (_outcome("validation_error", calculation_key="key-before"),), False),
            # Entries written before the key was stored cannot prove the metric is unchanged.
            ("no_stored_key", (_outcome("validation_error", calculation_key=None),), False),
            ("recovered_since", (_outcome(None, run="run-2"), _outcome("validation_error")), False),
            ("other_error_type", (_outcome("timeout"),), False),
            ("no_history", (), False),
        ]
    )
    def test_skip_unchanged_validation_error(
        self, name: str, outcomes: tuple[MetricRunOutcome, ...], expect_skip: bool
    ) -> None:
        skip = skip_unchanged_validation_error(_history(*outcomes))

        if expect_skip:
            assert skip == MetricSkip(
                reason=SKIP_REASON_UNCHANGED_VALIDATION_ERROR,
                skipped_error_type="validation_error",
                failed_recalculation_id="run-1",
                failed_at=_FAILED_AT,
            )
        else:
            assert skip is None
