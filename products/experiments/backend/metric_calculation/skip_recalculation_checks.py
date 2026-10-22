"""The checks that `skip_recalculation.find_metric_skips` runs, in order. Each check is pure."""

from typing import Final

from products.experiments.backend.metric_calculation.skip_recalculation import MetricHistory, MetricSkip, SkipCheck

VALIDATION_ERROR: Final = "validation_error"

SKIP_REASON_UNCHANGED_VALIDATION_ERROR: Final = "unchanged_validation_error"


def skip_unchanged_validation_error(history: MetricHistory) -> MetricSkip | None:
    """A validation error comes from the metric definition, so the metric fails again until its key changes."""
    latest = history.latest_outcome
    if latest is None or latest.error_type != VALIDATION_ERROR or latest.calculation_key != history.calculation_key:
        return None
    return MetricSkip(
        reason=SKIP_REASON_UNCHANGED_VALIDATION_ERROR,
        skipped_error_type=VALIDATION_ERROR,
        failed_recalculation_id=latest.recalculation_id,
        failed_at=latest.failed_at,
    )


RECALCULATION_SKIP_CHECKS: Final[tuple[SkipCheck, ...]] = (skip_unchanged_validation_error,)
